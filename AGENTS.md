# ngv-trader

Agentic software enabling one person to operate as a quick and nimble quantitative
futures, vol, and options trade desk.

This file holds the rules every change must follow. Detail lives in `docs/`:
[docs/contributing/](docs/contributing/README.md) covers the contributor workflow and
the [docs index](docs/README.md) lists everything else. Read the linked doc before
working in its area.

## Non-negotiables

- **Scope.** Do not change anything beyond what was explicitly requested. Do not
  remove, move, or restructure columns, fields, or UI elements unless asked. When in
  doubt, do less.
- **Database.** Every change to DB state (schema, views, indexes, constraints,
  seed/backfill data) is an Alembic migration, run with `task migrate ENV=<env>`.
  Never apply DDL or writes by hand; read-only `SELECT`s are fine. Snapshot before
  anything hard to reverse. See
  [database-migrations.md](docs/contributing/database-migrations.md).
- **Brokerage data.** Never commit real IBKR account IDs, conids, exec/order/
  transaction IDs, account aliases, or any account tied to real activity. Use the
  anonymized patterns and `<PLACEHOLDER>`s, and scan before staging. See
  [ibkr-sample-data.md](docs/ibkr-sample-data.md).
- **Secrets.** `.env.*` holds `op://` references. Scripts that read raw `os.environ`
  run under `op run --env-file=.env.<env> --`; migrations and `src/utils/env_vars.py`
  readers need no wrapper. FlexQuery tokens live encrypted in the DB, not in env. See
  [secrets-using-1password.md](docs/secrets-using-1password.md).
- **Python.** Always `uv run python`. Imports at the top of the file, type hints
  everywhere. Verify with `scripts/check.py`, Ruff, and Pyright; never run Python or
  shell to test code. New dependencies honor the 14-day cooldown. See
  [python-style.md](docs/contributing/python-style.md).
- **Commits and PRs.** Every commit and every PR title is a Conventional Commit;
  release-please parses them. PR bodies follow the required sections. See
  [commits-and-prs.md](docs/contributing/commits-and-prs.md).
- **Docs.** Indexes are generated: after adding, renaming, or deleting any
  `docs/**/*.md` (or changing its front matter), run `uv run python scripts/docs_index.py`.
  After any doc change, run `uv run python scripts/docs_check.py`. Specs carry a status
  banner and get rewritten or folded when they ship. See
  [docs-conventions.md](docs/contributing/docs-conventions.md).
- **Issues.** Beads (`bd`) is available but optional. If you use it, closing asserts
  the work is complete; otherwise leave the issue open and note what remains. See
  [issue-tracking.md](docs/contributing/issue-tracking.md).

## Quick commands

| Purpose                       | Command                                                                       |
| ----------------------------- | ----------------------------------------------------------------------------- |
| Import check (all / one)      | `uv run python scripts/check.py [src.services.jobs]`                          |
| Python tests                  | `task test -- -k api -v`                                                      |
| Frontend checks (`frontend/`) | `bun run typecheck && bun run lint && bun test && bun run build`              |
| Doc indexes / doc checks      | `uv run python scripts/docs_index.py` / `uv run python scripts/docs_check.py` |
| IBKR data scan (staged)       | `uv run python scripts/ibkr_sensitive_data_check.py`                          |
| Migrations                    | `task migrate ENV=dev` / `task migrate:new -- "desc"`                         |

What each check covers: [validation.md](docs/contributing/validation.md).

## Where to look

| Topic                                                   | Doc                                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------- |
| Repo layout, primitives, services, key files by concern | [codebase-map.md](docs/contributing/codebase-map.md)                |
| Domain vocabulary                                       | [CONCEPTS.md](CONCEPTS.md)                                          |
| Setup, architecture diagram, running locally            | [getting-started.md](docs/getting-started.md)                       |
| Workers and the job queue                               | [workers.md](docs/workers.md)                                       |
| Trade and execution sync                                | [trades-and-executions-sync.md](docs/trades-and-executions-sync.md) |
| Semantic layer, UX actions, pricing, SSE                | [docs/design/](docs/design/README.md)                               |
| Past problems and their fixes                           | [docs/solutions/](docs/solutions/README.md)                         |
| Doc review process                                      | [doc-review.md](docs/doc-review.md)                                 |
