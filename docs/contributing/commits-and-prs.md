---
topics: ["git", "commits", "pull-requests", "release"]
code_dirs_or_files:
  [
    "release-please-config.json",
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
Commit. release-please parses it to version and changelog the release.

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
intercepts `fetch` and answers every backend call from the fixtures in
`frontend/src/lib/demoData.ts` — so all pages render without a backend and
components need no demo-specific code. A "DEMO MODE" banner is shown so screenshots
are unambiguous.

**Capturing.** With the dev server running (`task frontend`):

```bash
cd frontend
node scripts/screenshot.mjs "/positions?demo=1" ../docs/screenshots/<name>.png [width] [height]
```

The script uses a preinstalled Chromium (Playwright's browser CDN is blocked by the
web egress policy — do **not** run `playwright install`). Commit the image under
`docs/screenshots/` and embed it in the PR body via its raw URL on the PR branch.

**Extending coverage.** If a changed view reads an endpoint the demo doesn't cover
yet, add a fixture to `demoData.ts` and a route to `routeGet` (or a write handler) in
`demoApi.ts` so the screenshot shows real content. Reuse the component/API types in
fixtures so they can't drift.
