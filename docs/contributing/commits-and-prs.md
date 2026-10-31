---
topics: ["git", "commits", "pull-requests", "release"]
code_dirs_or_files:
  [
    "release-please-config.json",
    ".github/settings/repo.json",
    "frontend/scripts/screenshot.mjs",
    "frontend/src/lib/demoApi.ts",
    "frontend/src/lib/demoData.ts",
  ]
description: Conventional Commit format for commits and PR titles (release-please parses them), the required PR body sections, and how to capture demo-mode UI screenshots.
---

# Commits and Pull Requests

## Commits

Write every commit as a Conventional Commit so release-please can version and
changelog it. Format: `<type>(<scope>): <imperative description>`.

Types (must match `release-please-config.json` `changelog-sections`): `feat`, `fix`,
`docs`, `refactor`, `chore`, `perf`, `test`, `ci`, `build`, `style`.

Scope is optional — a short area word like `trades`, `orders`, `api`, `db`, `ux`,
`workers`, `deps`. Use `BREAKING CHANGE:` in the body (or `!` after type/scope) for
breaking changes.

Rules: lowercase type/scope, imperative mood, no capital after the colon, keep the
subject under ~70 chars. Apply this to **each** commit, not just PR titles.

Examples: `feat(trades): add sync-since-last-trade button`,
`fix(workers): recover orphaned order jobs`, `docs: cross-check docs against codebase`.

## Pull request title

The PR title becomes the squash-merge commit subject, so it must be a Conventional
Commit. release-please parses it to version and changelog the release. The squash
body lists the branch's commit messages, and release-please reads conventional lines
there as extra changelog entries. Both settings are recorded in
`.github/settings/repo.json`; apply a change with
`gh api -X PATCH repos/westonplatter/ngv-trader --input .github/settings/repo.json`.

- Valid type (`feat`, `fix`, `docs`, `refactor`, `chore`, `perf`, `test`, `ci`, `build`, `style`); optional scope.
- Lowercase type/scope, imperative mood, no capital after the colon, subject under ~70 chars.
- Examples: `feat(frontend): move Trade Groups New button to left side`, `fix(tagging): allow groups across multiple accounts`.

## Pull request description

Include the following in the PR body:

- **Summary** (required). Less than 100 words. What changed and why (not a file list).
- **Features** (optional). Bullet list of new behavior/capabilities, or "N/A".
- **Refactoring** (optional). What changed and why; new code structure and patterns.
- **Fixes** (optional). Bullet list of bugs corrected/remediation, or "N/A".
- **Documentation** (required if behavior changed).
- **Additional notes** (when applicable). Link issue(s) or external resources.

## UI change screenshots (optional)

A PR that changes the frontend UI may include a screenshot of the net result,
captured with the built-in **demo data** (no live backend required). Not required —
add one when a picture makes the change easier to review.

**Demo mode.** Enable with the `?demo=1` URL query param (e.g. `/positions?demo=1`)
or `VITE_DEMO_MODE=1` in `frontend/.env`. When on, `frontend/src/lib/demoApi.ts`
swaps the API client's transport (`setApiFetch` in `frontend/src/lib/api.ts`) and
answers every backend call from the fixtures in `frontend/src/lib/demoData.ts` — so
all pages render without a backend and components need no demo-specific code. A "DEMO MODE" banner is shown so screenshots
are unambiguous.

**Capturing.** With the dev server running (`task frontend`):

```bash
cd frontend
node scripts/screenshot.mjs "/positions?demo=1" /tmp/<name>.png [width] [height]
```

The script uses a preinstalled Chromium (Playwright's browser CDN is blocked by the
web egress policy — do **not** run `playwright install`).

**Where images live.** Not on `main`: binaries stay out of the codebase. Commit
them to the `media` branch, which shares no history with `main` and is never
merged, under `screenshots/<feature>/`, and link them from the PR body or docs as
`https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/<feature>/<name>.png`.
Plain git push, so it needs no extra tooling or network setup. To add one without
switching branches:

```bash
git fetch origin media
git worktree add /tmp/media media
cp /tmp/<name>.png /tmp/media/screenshots/<feature>/
git -C /tmp/media add -A && git -C /tmp/media commit -m "docs: add <feature> screenshots"
git -C /tmp/media push origin media && git worktree remove /tmp/media
```

`git clone --single-branch` skips the branch. Older screenshots predating this
rule still sit in `docs/screenshots/` on `main`.

**Extending coverage.** If a changed view reads an endpoint the demo doesn't cover
yet, add a fixture to `demoData.ts` and a route to `routeGet` (or a write handler) in
`demoApi.ts` so the screenshot shows real content. Reuse the component/API types in
fixtures so they can't drift.
