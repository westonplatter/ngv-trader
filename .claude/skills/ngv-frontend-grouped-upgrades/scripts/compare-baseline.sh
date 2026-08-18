#!/usr/bin/env bash
# Compare frontend health metrics against a base ref.
#
# `main` carries pre-existing tsc/eslint failures (the frontend is not gated in
# CI), so the bar for a dependency PR is "unchanged", not "green". This measures
# both sides and diffs the counts.
#
# Uses a detached git worktree for the baseline -- never `git stash`, which
# silently applies an unrelated stale stash when the tree is clean.
#
# Usage:
#   compare-baseline.sh [base-ref]      # default: origin/main
set -uo pipefail

BASE_REF="${1:-origin/main}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
WORKTREE="$(mktemp -d)/baseline"

cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Measure one checkout: prints "build_errors lint_errors audit_vulns"
measure() {
  local dir="$1/frontend"
  [ -d "$dir" ] || { echo "n/a n/a n/a"; return; }

  ( cd "$dir" && bun install ) >/dev/null 2>&1

  local build lint audit
  build=$( cd "$dir" && bun run build 2>&1 | grep -c "error TS" )
  lint=$( cd "$dir" && bun run lint 2>&1 | grep -oE "[0-9]+ error" | head -1 | grep -oE "[0-9]+" )
  audit=$( cd "$dir" && bun audit 2>&1 | grep -oE "^[0-9]+ vulnerabilit" | grep -oE "^[0-9]+" )

  echo "${build:-0} ${lint:-0} ${audit:-0}"
}

echo "Building baseline worktree at ${BASE_REF}..."
git -C "$REPO_ROOT" fetch -q origin 2>/dev/null || true
if ! git -C "$REPO_ROOT" worktree add --detach -q "$WORKTREE" "$BASE_REF" 2>/dev/null; then
  echo "ERROR: could not create worktree at '${BASE_REF}'." >&2
  exit 1
fi

read -r base_build base_lint base_audit <<<"$(measure "$WORKTREE")"
read -r cur_build cur_lint cur_audit <<<"$(measure "$REPO_ROOT")"

# Restore the working tree's own dependencies -- the baseline run reinstalled
# from the base ref's lockfile into a separate dir, but be explicit.
( cd "$REPO_ROOT/frontend" && bun install ) >/dev/null 2>&1

verdict() { # $1=base $2=current  -> SAME / BETTER / WORSE
  if [ "$1" = "$2" ]; then echo "same"
  elif [ "$2" -lt "$1" ] 2>/dev/null; then echo "BETTER (-$(($1 - $2)))"
  else echo "WORSE (+$(($2 - $1)))"
  fi
}

printf '\n%-16s %10s %10s   %s\n' "metric" "$BASE_REF" "working" "verdict"
printf '%-16s %10s %10s   %s\n' "----------------" "----------" "----------" "-------"
printf '%-16s %10s %10s   %s\n' "build (tsc -b)" "$base_build" "$cur_build" "$(verdict "$base_build" "$cur_build")"
printf '%-16s %10s %10s   %s\n' "lint (eslint)"  "$base_lint"  "$cur_lint"  "$(verdict "$base_lint" "$cur_lint")"
printf '%-16s %10s %10s   %s\n' "bun audit"      "$base_audit" "$cur_audit" "$(verdict "$base_audit" "$cur_audit")"

echo
if [ "$cur_build" -gt "$base_build" ] 2>/dev/null || [ "$cur_lint" -gt "$base_lint" ] 2>/dev/null; then
  echo "REGRESSION: build or lint got worse than ${BASE_REF}. Do not ship."
  exit 1
fi
echo "OK: no regression vs ${BASE_REF}. Cite these counts in the PR body."
