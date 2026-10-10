---
topics: ["testing", "ci", "validation", "quality-gates"]
code_dirs_or_files:
  [
    "scripts/check.py",
    "scripts/docs_check.py",
    "scripts/ibkr_sensitive_data_check.py",
    "tests/",
    ".github/workflows/tests.yml",
    ".trunk/trunk.yaml",
  ]
description: Every check a change must pass before it ships — import checks, pytest, frontend checks, doc checks, and the IBKR sensitive-data scan — with the commands and what each covers.
---

# Validation

Run the checks that match what you touched. CI runs the Python and frontend
suites on every PR; the rest are local gates.

| Changed            | Run                                                              |
| ------------------ | ---------------------------------------------------------------- |
| Any Python         | `uv run python scripts/check.py`, Ruff, Pyright                  |
| Python behavior    | `task test`                                                      |
| `frontend/`        | `bun run typecheck && bun run lint && bun test && bun run build` |
| Any doc            | `uv run python scripts/docs_check.py`                            |
| Anything to commit | `uv run python scripts/ibkr_sensitive_data_check.py`             |

## Import checks

Always use `uv run python scripts/check.py <module>` to verify imports. Never use
`uv run python -c` for import checks.

- All modules: `uv run python scripts/check.py`
- Specific: `uv run python scripts/check.py src.services.jobs`

Exits 1 on failure.

Use Ruff for fast feedback during edits. Pyright must pass before declaring changes
correct. Never run Python or shell to test code.

## Python tests

`task test` runs the pytest suite (`tests/`). Pass pytest args after `--`, e.g.
`task test -- -k api -v`.

Tests never touch dev or prod data. `tests/conftest.py` reads connection settings
from `.env.dev` (override with `TEST_ENV_FILE`), then forces `DB_NAME` to
**`ngv_trader_test`** (override with `TEST_DB_NAME`) and aborts if the name does not
end in `_test`. The database is created if missing and migrated with
`alembic upgrade head`; each test runs in a transaction that is rolled back.

The suite is a dependency-bump canary (see `.github/dependabot.yml`): every `src/`
module imports, migrations reach head and cover every model table, an ORM round-trip
works, and the API serves `/api/v1/health` and `/openapi.json`. Because
`[tool.uv] default-groups = []`, tests must run as
`uv run --group dev --extra mcp pytest` — a bare `uv run pytest` prunes pytest and
the `mcp` extra.

CI runs the same suite on every PR and push to `main` via
`.github/workflows/tests.yml`, against a Postgres 17 service container. There,
`TEST_ENV_FILE` points at a nonexistent file so no `.env` is loaded and `DB_*` come
from the workflow env.

## Frontend checks

The same workflow runs a `frontend` job over `frontend/`:
`bun install --frozen-lockfile`, then `bun run typecheck`, `bun run lint`,
`bun test`, `bun run build`. Run those four locally before pushing frontend
changes — `task test` covers only the Python suite.

`typecheck` is `tsc -b --force`, not `tsc --noEmit`: the root `tsconfig.json` is a
solution file (`files: []`, references only), so `--noEmit` against it checks
nothing and always exits 0.

## Doc checks

After any doc change, run `scripts/docs_check.py` to catch broken links, missing
script paths, bad task commands, and missing spec banners.

- All checks: `uv run python scripts/docs_check.py`
- Include undocumented routes (informational): `uv run python scripts/docs_check.py --routes`
- Specific check: `uv run python scripts/docs_check.py links`

Exits 1 on hard failures (`FAIL`). Route warnings are `WARN` only — not blockers.
Index regeneration and the spec lifecycle are in
[docs-conventions.md](docs-conventions.md).

## IBKR sensitive-data scan

Before staging, scan changes for real IBKR identifiers that must never be committed
(patterns and policy in [ibkr-sample-data.md](../ibkr-sample-data.md)).

- Staged changes: `uv run python scripts/ibkr_sensitive_data_check.py`
- Include untracked files: `uv run python scripts/ibkr_sensitive_data_check.py --untracked`
- Specific files/dirs in full: `uv run python scripts/ibkr_sensitive_data_check.py --paths <path> ...` (directories recurse, honoring `.gitignore`)
- Result only, no per-file list: `uv run python scripts/ibkr_sensitive_data_check.py --quiet`

Every scanned file is listed by default so the output is evidence of what was
checked; `--quiet` drops that list but still prints findings.

Flags account IDs, contract IDs, and execution/transaction/order IDs. Prices,
quantities, symbols, and exchanges are intentionally not flagged — those stay real.
Exits 1 on findings.

### Pre-commit hook

The same scan runs automatically on every commit, as the trunk action
`ibkr-sensitive-data-check` (`.trunk/trunk.yaml`). A commit whose staged diff
contains a real identifier is rejected before it lands.

Trunk owns `core.hooksPath`, so hooks live outside `.git/hooks` and each clone
must opt in once:

```bash
trunk git-hooks sync
```

The hook shells out to `python3` rather than `uv run` — the script is pure
stdlib, so it gates a commit on a machine with no virtualenv synced.

Two limits worth knowing: `git commit --no-verify` skips it, and a contributor
who never runs `trunk git-hooks sync` never has it. It catches honest mistakes;
it is not an enforcement boundary.
