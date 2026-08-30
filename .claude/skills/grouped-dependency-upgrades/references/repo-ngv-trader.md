# Repo notes: ngv-trader

Local facts the portable skill deliberately does not hardcode.

## Conventions live in AGENTS.md

Commit format (Conventional Commits), PR body sections, the 14-day cooldown,
and the IBKR data rules are all there. Read it before shipping.

## The base branch is red, in both ecosystems

Neither the frontend build/lint nor `ruff` is gated in CI —
`.github/workflows/tests.yml` runs pytest only. Measured on `origin/main`:

| adapter | metric | baseline (2026-08-29) |
| --- | --- | --- |
| bun | build (`tsc -b`) | 0 errors |
| bun | lint (eslint) | 1 error |
| bun | audit | 2 vulnerabilities |
| uv | imports (`scripts/check.py`) | 0 failed of 73 modules |
| uv | lint (`ruff check .`) | 76 errors |
| uv | tests (`pytest`) | 245 passed |

These drift — re-measure rather than quoting this table in a PR. The frontend
build was 17 errors a few days earlier (demo fixtures in
`frontend/src/lib/demoData.ts` drifted from the `Position`/`TradeGroup` types);
#219 fixed them. That drift is the point of the table's caveat, not an
exception to it.

**A stale branch shows up as a regression.** The first bun baseline of this
batch read `build WORSE (+17), lint WORSE (+12)` on a tree with no frontend
change at all: the working branch predated #219 while `origin/main` did not.
`git diff origin/main...HEAD` will not show it — three-dot diffs from the merge
base hide what main gained. Branch fresh from `origin/main` and re-measure
before reading a regression as your own.

**Worked example of the drift.** These numbers moved twice in a single session:
`#180` (`@types/react-dom` patch) took the build from 18 to 17, and `#186`
(`eslint-plugin-react-hooks` 7.0.1 → 7.1.1, a dev patch) took lint from 6 to 13
with no source change at all. The second is why `eslint-plugin-react-hooks` is
in the bun adapter's `baseline_tools`.

## The Python suite needs infrastructure this environment lacks

Claude Code web sessions have no Postgres and no `.env.dev`, so the uv `tests`
metric reports UNMEASURABLE. Run the Python side as
`--metrics imports,lint` there and say so in the PR, rather than letting a
skipped check read as a passing one.

On a workstation with Postgres running it does work end to end — 245 tests, DB
created and migrated by `tests/conftest.py`. Running it there is what exposed
the `-qq` bug: `pyproject.toml` sets `addopts = "-q"`, so the adapter's own
`-q` made it `-qq`, which suppresses the `N failed ... in Xs` summary line the
metric parses. A green suite still scored 0 (correct by luck, via exit 0), but
a *failing* suite scored UNMEASURABLE instead of a count. The adapter now runs
`pytest` with no `-q` of its own.

## No `gh` in web or mobile sessions

Claude Code on the web has no GitHub CLI. Use the GitHub MCP tools:
`list_pull_requests` to triage (feed the JSON to `triage_prs.py --from-file`),
`update_pull_request` with `state: "closed"` plus `add_issue_comment` to close
superseded PRs.

## Tracking

Batches are tracked in kata: `--project ngv-tradrer` (the registered name
carries a typo; see AGENTS.md). One issue per batch, listing the grouped PR
numbers and the ones deliberately left out. Close it only after the grouped PR
merges and the superseded PRs are closed.

## Pre-commit

Trunk runs the IBKR sensitive-data scan on every commit. Dependency PRs never
trip it, but a `--paths` scan before staging costs nothing:
`uv run python scripts/ibkr_sensitive_data_check.py`.
