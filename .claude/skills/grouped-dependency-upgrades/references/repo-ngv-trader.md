# Repo notes: ngv-trader

Local facts the portable skill deliberately does not hardcode.

## Conventions live in AGENTS.md

Commit format (Conventional Commits), PR body sections, the 14-day cooldown,
and the IBKR data rules are all there. Read it before shipping.

## The base branch is red, in both ecosystems

Neither the frontend build/lint nor `ruff` is gated in CI —
`.github/workflows/tests.yml` runs pytest only. Measured on `origin/main`:

| adapter | metric | baseline |
| --- | --- | --- |
| bun | build (`tsc -b`) | 18 errors |
| bun | lint (eslint) | 13 errors |
| bun | audit | 2 vulnerabilities |
| uv | imports (`scripts/check.py`) | 0 failed of 73 modules |
| uv | lint (`ruff check .`) | ~81 errors |

These drift; re-measure rather than quoting this table in a PR. The frontend
`tsc -b` errors are demo fixtures in `frontend/src/lib/demoData.ts` drifted from
the `Position`/`TradeGroup` types — a separate PR, not part of a dep bump.

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
