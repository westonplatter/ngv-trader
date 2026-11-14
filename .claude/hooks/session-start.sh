#!/bin/bash
# SessionStart hook: install backend + frontend deps so tests/linters work.
# Runs in Claude Code on the web, and locally in a git worktree that has no
# deps yet (a new worktree is a clean checkout: no .venv, no node_modules).
# Idempotent and non-interactive.
set -euo pipefail

install_deps() {
  cd "$1"

  # Backend: sync Python deps incl. the dev group (typer/ruff/ipdb).
  # pyproject sets default-groups = [], so --group dev is required for
  # scripts/check.py (typer) and ruff to be available.
  echo "[session-start] uv sync --group dev"
  uv sync --group dev

  # Frontend: install JS deps with bun.
  echo "[session-start] bun install (frontend)"
  (cd frontend && bun install)

  echo "[session-start] done"
}

if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  install_deps "$CLAUDE_PROJECT_DIR"
  exit 0
fi

# Local: act only inside a linked git worktree. $CLAUDE_PROJECT_DIR can still
# point at the main checkout, so take the session's directory from the hook
# input (`cwd`) when jq is available, else from the process.
session_dir="$PWD"
if [ ! -t 0 ] && command -v jq >/dev/null 2>&1; then
  input_cwd="$(jq -r '.cwd // empty' 2>/dev/null || true)"
  if [ -n "$input_cwd" ]; then
    session_dir="$input_cwd"
  fi
fi

top="$(git -C "$session_dir" rev-parse --show-toplevel 2>/dev/null || true)"

# A linked worktree's .git is a file; the main checkout's is a directory.
if [ -z "$top" ] || [ ! -f "$top/.git" ]; then
  exit 0
fi

if [ -d "$top/.venv" ] && [ -d "$top/frontend/node_modules" ]; then
  exit 0
fi

install_deps "$top"
