# ngv-trader

Agentic software enabling one person to operate as an quick and nimble quantative futures, vol. and options trade desk.

## Docs Index Rule

Doc indexes are generated. If any `docs/**/*.md` file is added, renamed, or deleted (or its front-matter `description`/`topics` changes), regenerate the indexes in the same change:

```bash
uv run python scripts/docs_index.py
```

This writes a `README.md` into `docs/` and every docs subdirectory that contains `.md` files (GitHub auto-renders these), `docs/core/` included. Index files are generated artifacts — never edit them by hand. Front matter (`topics`, `description`) is optional; docs without it are still listed.

Every `spec-*.md` carries a status banner at the top (e.g. `Status: NOT IMPLEMENTED` / `PARTIAL`).

When a spec ships, do the wrap-up in the same change:

1. Rewrite it to describe the system as it works today, or fold it into the relevant current-state doc.
2. If kept as a standalone file, remove the `spec-` prefix; if folded, delete the spec file.
3. Update any in-repo references to the old filename.
4. Regenerate the indexes.

When writing documentation or summaries, default to high-level overviews that point to detailed resources rather than verbose step-by-step instructions. Avoid hardcoding filenames in docs when the user wants lightweight guidance.

## Issue Tracking (kata)

Work in this repo is tracked in [kata](https://www.katatracker.com), a local
issue ledger driven by the `kata` CLI. Issues are referenced by short id
(e.g. `y8t3`), not numbers.

**The registered project name is `ngv-tradrer`** (a typo that predates the
binding) while `.kata.toml` declares `ngv-trader`, so workspace resolution
fails. Pass `--project ngv-tradrer` on every project-scoped command until the
project is renamed:

```bash
kata show y8t3 --project ngv-tradrer --agent      # read an issue + comments
kata next --unowned --project ngv-tradrer --agent # find ready, unowned work
kata claim y8t3 --project ngv-tradrer --agent     # take ownership
kata comment y8t3 --project ngv-tradrer --body "approach notes" --agent
kata search "trade group" --project ngv-tradrer --agent
```

Conventions:

- Pass `--agent` for ordinary reads and mutations; `--json` only when piping to `jq`.
- Search before creating, and pass `--idempotency-key` on `kata create` so retries don't duplicate.
- **Closing asserts the work is complete.** If it isn't, do not close — add
  `kata label add <ref> needs-review` plus a comment saying what remains.
- Close each issue as its own work is verified, with evidence:

  ```bash
  kata close y8t3 --project ngv-tradrer --done \
    --message "What changed and how it was verified." \
    --commit "$(git rev-parse HEAD)" \
    --test "bunx tsc --noEmit" \
    --agent
  ```

- `kata quickstart` prints the full agent contract; `kata --help` lists all commands.
- The MCP server (`kata mcp serve`) is not registered in `.mcp.json` — use the CLI.

## Issue Tracking (beads)

Issues also live in [beads](https://beads.gascity.com/getting-started/quickstart) —
a dependency-aware ledger stored in an embedded Dolt database under `.beads/`
and driven by the `bd` CLI. Ids are hash-based and prefixed with the repo
(e.g. `ngv-trader-xms`), not numbers. There is no `--project` flag: `bd` walks
up from the cwd to find `.beads/`.

Adding an issue:

```bash
bd create "Add 3 Days trade sync button to Trades page" \
  -t feature -p 2 -l "frontend,trades" \
  -d "What changes and where, with file paths." \
  --acceptance "Observable done condition."
```

- `-t` type: `task` (default), `bug`, `feature`, `chore`, `epic`, `decision`, `spike`, `story`. `bd types` lists them.
- `-p` priority: `0`–`4`, 0 highest, default `2`.
- `-l` labels: comma-separated.
- `--parent <id>` files a child under an epic; `--deps 'blocks:<id>'` (or `bd dep add <id> <blocker>`) records a blocker.
- `--silent` prints only the new id — use it when scripting. `--dry-run` previews.

Search before creating: `bd search "trade sync"`, `bd find-duplicates`.

Working the queue:

```bash
bd ready                                  # open issues with no active blockers
bd list --status open
bd show ngv-trader-xms
bd update ngv-trader-xms --claim          # assign to self + in_progress
bd note ngv-trader-xms "approach notes"
bd close ngv-trader-xms --reason "Shipped in PR #199; verified with bunx tsc --noEmit"
```

Conventions:

- Write descriptions a fresh agent can act on: file paths, the observable behavior, acceptance criteria.
- **Closing asserts the work is complete.** If it isn't, leave it open and `bd note <id> "what remains"`.
- Add `--json` to any command when piping to `jq`; plain output otherwise.
- `bd prime` prints the full agent workflow contract; `bd quickstart` is the short version.
- Sync is Dolt-native (`bd dolt push` / `bd dolt pull`). Git hooks are not installed in this clone — `bd hooks install` to opt in.

## Task Delegation

Do NOT make changes beyond what was explicitly requested. Do not proactively remove, move, or restructure columns, fields, or UI elements unless specifically asked. When in doubt, do less.

## Database Changes

### No ad-hoc DB changes — migrations only

**Every change to database state (schema, views, indexes, constraints, seed/backfill
data) MUST go through an Alembic migration.** Never apply DDL or data changes to a
database directly — no `psql`/`CREATE`/`ALTER`/`DROP`/`UPDATE` run by hand, no
`CREATE TEMP VIEW` to "just check" against a real DB, no ORM one-off scripts that
mutate. This includes the semantic-layer `v_*` views. Migrations are the only
reviewable, reversible, reproducible record of DB state. Read-only `SELECT`s for
inspecting data are fine; anything that writes or defines structure is a migration.

### Running Migrations

This project uses **Alembic**, driven through the Taskfile. To run migrations, use the task command (which auto-loads `.env.<ENV>`), not raw `alembic`:

- Prod: `task migrate ENV=prod`
- Dev: `task migrate ENV=dev`

"Run the migrations in prod" means `task migrate ENV=prod`. No `op run` wrapper is needed — the DB URL is built from plain `DB_HOST`/`DB_USER`/`DB_PASSWORD`, not `op://` secrets. Related: `task migrate:down` (downgrade one), `task migrate:new -- "desc"` (autogenerate), `task validate`.

### Authoring Migrations

Generate the file with `task migrate:new -- "<desc>"`, then edit only the docstring, mapping constants, and `upgrade()`/`downgrade()` bodies. Never hand-author a revision or touch the auto-assigned `revision`/`down_revision` — hand-picked IDs collide with existing ones.

### Snapshots

Before any hard-to-reverse DB change (destructive/data-mutating migration, backfill, prod `downgrade`, bulk delete), take a Postgres snapshot first. See [docs/db-snapshots.md](docs/db-snapshots.md) for the snapshot/verify/restore commands and the recommended flow.

## Secrets (1Password)

`.env.*` files store secrets as 1Password URIs (`OPENAI_API_KEY=op://ngtrader_pro/OPENAI_API_KEY/value`). `load_dotenv` yields the literal string; vars read through raw `os.environ` need `op run` to resolve them at exec time:

```bash
op run --env-file=.env.<env> -- uv run python scripts/<script>.py
```

Vars read through `src/utils/env_vars.py` — `FLEX_TOKEN_ENCRYPTION_KEY`, `BROKER_TWS_PORT`, `TRADEBOT_LLM_API_KEY` — self-resolve `op://` and need no wrapper. Migrations are exempt (plain `DB_*` vars). See [docs/secrets-using-1password.md](docs/secrets-using-1password.md).

IBKR FlexQuery tokens are **not** environment variables. They live encrypted at rest in the `flexquery_tokens` table; `FLEX_TOKEN_ENCRYPTION_KEY` is what decrypts them, and a job payload cannot supply one. Manage them with `scripts/manage_flex_tokens.py`.

## Sample Data (IBKR anonymization)

This repo handles personal brokerage data. **Never commit real IBKR account IDs, conids, exec/transaction/order IDs, prices, or trading dates.** Any repo-bound example/fixture/doc must use the anonymized patterns in `docs/ibkr-sample-data.md` — e.g. accounts `U1234567`, generic ID ranges (`1000000001`), `ibExecID` `0000abcd.12345678.01.01`, generic Jan 2025 dates. Keep real for shape: symbols, exchanges, sec types, realistic prices/quantities.

`scripts/data/` is gitignored for ad-hoc real CSVs — never commit them. Before `git add`, scan staged additions for real-looking IDs (10-digit txn IDs, `U`-prefixed accounts, hex exec IDs).

### Genericize account references in plans and docs

This applies to written content committed to the repo — plans, specs, docs, code
comments, fixtures, commit messages.

Accounts carry a short **alias** (`accounts.alias`) so the UI and semantic model never
show the raw `U…` number. Naming the _column_ is fine; writing a _specific_ alias into
committed content is not — not in prose, not in a filename or title, not even without
data attached. Aliases are stable, few, and identifying in aggregate; keeping them out
of the repo is simpler than judging each mention. In chat, scratchpad files, and
gitignored paths, use whatever alias you need.

Worse still is any account reference — an alias, or "the account that…" — tied to real
**activity**. A plan must not pin an account to concrete holdings, quantities, average
costs, P&L, execution counts, import windows, trade dates, or prod row ids — together
those profile a real account even with every IBKR identifier redacted, and
`scripts/ibkr_sensitive_data_check.py` does **not** catch it.

Write plans against placeholders instead: `<ACCOUNT>`, `<CONID>`, `<QTY>`,
`<AVG_COST>`, `<TRADE_ID>`, `<DAILY_START>`. Keep the _shape_ of the problem — the
mechanics, the failure mode, the procedure — and keep symbols, sec types, and
exchanges real. Concrete values, aliases included, belong in gitignored `scratchpad/`,
referenced by path.

See `docs/plans/2026-07-14-001-fix-missing-opening-execution-plan.md` for the pattern:
a full recovery runbook that names no account and loses no usefulness.

## Code Validation

Always use `uv run python scripts/check.py <module>` to verify imports. Never use `uv run python -c` for import checks.

- All modules: `uv run python scripts/check.py`
- Specific: `uv run python scripts/check.py src.services.jobs`

Exits 1 on failure.

## Tests

`task test` runs the pytest suite (`tests/`). Pass pytest args after `--`, e.g. `task test -- -k api -v`.

Tests never touch dev or prod data. `tests/conftest.py` reads connection settings from `.env.dev` (override with `TEST_ENV_FILE`), then forces `DB_NAME` to **`ngv_trader_test`** (override with `TEST_DB_NAME`) and aborts if the name does not end in `_test`. The database is created if missing and migrated with `alembic upgrade head`; each test runs in a transaction that is rolled back.

The suite is a dependency-bump canary (see `.github/dependabot.yml`): every `src/` module imports, migrations reach head and cover every model table, an ORM round-trip works, and the API serves `/api/v1/health` and `/openapi.json`. Because `[tool.uv] default-groups = []`, tests must run as `uv run --group dev --extra mcp pytest` — a bare `uv run pytest` prunes pytest and the `mcp` extra.

CI runs the same suite on every PR and push to `main` via `.github/workflows/tests.yml`, against a Postgres 17 service container. There, `TEST_ENV_FILE` points at a nonexistent file so no `.env` is loaded and `DB_*` come from the workflow env.

## Doc Validation

After any doc change, run `scripts/docs_check.py` to catch broken links, missing script paths, bad task commands, and missing spec banners.

- All checks: `uv run python scripts/docs_check.py`
- Include undocumented routes (informational): `uv run python scripts/docs_check.py --routes`
- Specific check: `uv run python scripts/docs_check.py links`

Exits 1 on hard failures (`FAIL`). Route warnings are `WARN` only — not blockers.

## IBKR Data Check

Before staging, scan changes for real IBKR identifiers that must never be committed (see **Sample Data** above).

- Staged changes: `uv run python scripts/ibkr_sensitive_data_check.py`
- Include untracked files: `uv run python scripts/ibkr_sensitive_data_check.py --untracked`
- Specific files/dirs in full: `uv run python scripts/ibkr_sensitive_data_check.py --paths <path> ...` (directories recurse, honoring `.gitignore`)
- Result only, no per-file list: `uv run python scripts/ibkr_sensitive_data_check.py --quiet`

Every scanned file is listed by default so the output is evidence of what was checked; `--quiet` drops that list but still prints findings.

Flags account IDs, contract IDs, and execution/transaction/order IDs against the patterns in `docs/ibkr-sample-data.md`. Prices, quantities, symbols, and exchanges are intentionally not flagged — those stay real. Exits 1 on findings.

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

## Codebase Survey

### Repository Layout

- `src/`: Python backend application code (current import root is `src`).
- `scripts/`: operator-facing workflows and broker/database utilities.
- `alembic/` + `alembic.ini`: database migrations for Postgres schema.
- `frontend/`: React + Vite UI (positions, orders, trades, strategies, pricing, tradebot chat).
- `docs/`: current-state docs and specs; see `docs/_index.md`.
- `docs/solutions/`: documented solutions to past problems (bugs, best practices, workflow patterns), organized by category with YAML frontmatter (`module`, `tags`, `problem_type`) — relevant when implementing or debugging in documented areas.
- `CONCEPTS.md`: shared domain vocabulary (entities, named processes, status concepts) — relevant when orienting to the codebase or discussing domain concepts.
- `tests/`: pytest suite run via `task test` against a dedicated `ngv_trader_test` database.
- `Taskfile.yaml`: common dev commands for API, frontend, migrations, and tests.

### Primitives

- `src/db.py`: DB URL and SQLAlchemy engine builders (`get_database_url`, `get_engine`).
- `src/utils/ibkr_account.py`: account masking helper (`mask_ibkr_account`) for safer logs.
- `src/utils/contract_display.py`: human-readable contract labels (`contract_display_name`).
- `src/utils/env_vars.py`: typed env-var helpers.
- `src/services/sync_common.py`: shared sync helpers (id parsing, account upsert, canonical flags, aggregates).

### Components

- `src/models.py`: SQLAlchemy `Base` plus all entities (single source for table structure). Beyond `Position`: `ContractRef`, `ActivatedProduct`, `Account`, `Order`/`OrderEvent`, `Job`, `Trade`/`TradeExecution`, `FlexSyncLog`, `TradeGroup*`/`Tag*` (tagging), `WatchList*`, market-data `LatestFutures*`/`TsFutures*`, `OptionChainMeta`, `SavedStructure`, `UserPreference`, `WorkerHeartbeat`, intraday overlay `LivePosition`/`LatestQuote`/`LiveExecution`/`LatestOptionMetrics`.
- `src/schemas.py`: Pandera DataFrame schema for positions validation shape.
- `src/api/deps.py`: FastAPI DB session dependency (`get_db`).
- `src/api/routers/*.py`: REST surface — `positions`, `orders`, `trades`, `futures` (market data), `activated_products`, `jobs`, `workers`, `events` (SSE), `tradebot` (chat), `watch_lists`, `tags`, `trade_groups`, `accounts`, `structures`, `reports`, `admin`, `user_preferences`, `flexquery_tokens`.
- `frontend/src/components/*.tsx`: React UI (positions, orders, trades, strategies, pricing, tradebot chat) consuming `/api/v1/*`.

### Services

- `worker:jobs` (`scripts/work_jobs.py` shim → `src/workers/jobs.py`): background job handlers — FlexQuery trade/position sync, market data, contracts, watchlists, order fetch. Queue primitive `src/services/jobs.py`.
- `worker:orders` (`scripts/work_order_queue.py`): order-lifecycle scaffold; **submission is disabled** (see `docs/workers.md`).
- Sync services: `src/services/{trade,position}_sync_flexquery.py` (active), `..._tws.py` (dormant), `contract_sync.py`, `market_data.py`.
- `src/services/tradebot_agent.py`: LangGraph chat agent (DB reads + job enqueue; no `ib_async` import).
- Operator utilities: `scripts/setup_db.py` (DB + migrations), `scripts/download_positions.py` (one-time TWS position bootstrap), `scripts/fetch_flex_trades.py`, `scripts/test_tws_connection.py`, `scripts/validate_env.py`.
- `src/api/main.py`: FastAPI entrypoint (`task api` or `uv run uvicorn src.api.main:app --reload --port 8000`).
- `frontend/` dev server: UI service (`task frontend` or `bun run dev` in `frontend/`).

### End-to-End Workflow (Current)

1. Run `scripts/setup_db.py` to ensure DB + migrations are current.
2. (Optional) Start IBKR TWS/Gateway and run `scripts/download_positions.py` for a one-time position bootstrap.
3. Run backend API (`src/api/main.py`) and frontend (`frontend/`).
4. Run `worker:jobs` for ongoing sync; trades/positions sync via FlexQuery (no local broker session required).

### Key Files By Concern

- Broker integration: `src/services/{trade,position}_sync_flexquery.py`, `src/services/flex_client_factory.py`, `src/services/contract_sync.py`, `scripts/fetch_flex_trades.py`, `scripts/test_tws_connection.py`
- Data model/storage: `src/models.py`, `src/db.py`, `alembic/versions/`
- API surface: `src/api/main.py`, `src/api/routers/`
- UI surface: `frontend/src/App.tsx`, `frontend/src/components/`
- Workers/jobs: `src/workers/jobs.py`, `src/services/jobs.py`, `scripts/work_jobs.py`, `scripts/work_order_queue.py`
- Ops docs: `docs/getting-started.md`, `docs/workers.md`, `docs/trades-and-executions-sync.md`, `docs/secrets-using-1password.md`

### Active Architecture Direction

- Current import root is `src` (`from src...`). A previously-planned migration to an installable `src/ngv_trader/...` package layout has no active spec on disk; re-add one under `docs/spec-*.md` before resuming that work.

## Python

### Verifying Code

- Never run Python or shell to test code
- Use Ruff for fast feedback during edits
- Require Pyright to pass before declaring changes correct

### Code Organization

- Always place python imports at top of file
- Never import packages in functions

### Package Installation Cooldown

A **14-day cooldown** applies to all new dependencies (Python and JS) to avoid
ingesting freshly-published, potentially-compromised versions.

**Python (uv):** enforce the cutoff at add time:

```bash
uv add <pkg> --exclude-newer "$(date -u -d '14 days ago' +%Y-%m-%d)"
```

1. Applies to direct dependencies only; transitive upgrades pulled in by `uv sync` are exempt.
2. Note the cooldown and the release date in the PR description when adding a new package.

**Frontend (bun):** enforced mechanically — `frontend/bunfig.toml` sets
`minimumReleaseAge = 1209600` (14 days), so `bun add`/`bun install` refuse any
version published less than 14 days ago. No manual step needed. To intentionally
allow a fresh package, add it to `minimumReleaseAgeExcludes` in `bunfig.toml` and
note it in the PR.

This prevents ingesting packages with undetected supply-chain issues or breaking changes in the days immediately after release.

### Principles

1. **Use `uv run python`** - Always execute Python commands via `uv run python ...` to ensure consistent dependency management and virtual environment isolation.
2. **Type hints everywhere** - Use type annotations for function signatures and variables to improve code clarity and enable better static analysis.
3. **Prefer standard library** - Use Python's standard library when possible before reaching for third-party packages. This reduces dependencies and improves portability.
4. **Explicit over implicit** - Write clear, readable code that makes intent obvious. Avoid magic methods and metaprogramming unless there's a compelling reason.

### Progress Bars

Use `tqdm` for user-facing scripts or long-running processes to provide feedback.
To keep log statements above the progress bar (preventing visual conflicts):

```python
from tqdm import tqdm

for item in tqdm(items, desc="Processing"):
    # Use tqdm.write() instead of print() for log messages
    tqdm.write(f"Processing {item.name}")
    process(item)
```

For logging module integration:

```python
import logging
from tqdm import tqdm

# Redirect logging through tqdm
class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        tqdm.write(self.format(record))

logging.basicConfig(handlers=[TqdmLoggingHandler()], level=logging.INFO)
```

## Pandas

### Pandas Principles

1. **Use vectorized operations** - Avoid iterating over rows with `for` loops or `.iterrows()`. Use built-in vectorized methods for performance.

2. **Chain methods** - Use method chaining (`.pipe()`, `.assign()`, `.query()`) for readable, declarative transformations.

3. **Be explicit with dtypes** - Specify dtypes when reading data and use `.astype()` to enforce types. This prevents silent type coercion bugs.

4. **Prefer `.loc` and `.iloc`** - Use explicit indexing instead of chained indexing to avoid `SettingWithCopyWarning` and ensure predictable behavior.

5. **Handle missing data intentionally** - Use `.isna()`, `.fillna()`, or `.dropna()` explicitly. Never assume data is complete.

6. **Use `.copy()` when needed** - Create explicit copies when modifying subsets to avoid unintended mutations to the original DataFrame.

## Docs Style

Compact, high signal to noise write descriptions optimized for an engineer-to-engineer dialogue.

- Be concise. Prefer short sentences and direct statements.
- Focus on actionable information. Avoid filler, marketing, and verbosity.
- Use plain language and concrete terms.
- Keep sections small; remove anything nonessential.
- Use bullets for quick scanning; avoid long paragraphs.
- Favor commands/examples over prose.
- State assumptions explicitly when needed.
- Avoid redundancy.

## Commits

Write every commit as a Conventional Commit so release-please can version and changelog it. Format: `<type>(<scope>): <imperative description>`.

Types (must match `release-please-config.json` `changelog-sections`): `feat`, `fix`, `docs`, `refactor`, `chore`, `perf`, `test`, `ci`, `build`, `style`.

Scope is optional — a short area word like `trades`, `orders`, `api`, `db`, `ux`, `workers`, `deps`. Use `BREAKING CHANGE:` in the body (or `!` after type/scope) for breaking changes.

Rules: lowercase type/scope, imperative mood, no capital after the colon, keep the subject under ~70 chars. Apply this to **each** commit, not just PR titles.

Examples: `feat(trades): add sync-since-last-trade button`, `fix(workers): recover orphaned order jobs`, `docs: cross-check docs against codebase`.

## Pull Requests

### Pull Request Title

The PR title becomes the squash-merge commit subject, so it must be a Conventional Commit (see **Commits** above): `<type>(<scope>): <imperative description>`. release-please parses it to version and changelog the release.

- Use a valid type (`feat`, `fix`, `docs`, `refactor`, `chore`, `perf`, `test`, `ci`, `build`, `style`); optional scope.
- Lowercase type/scope, imperative mood, no capital after the colon, subject under ~70 chars.
- Examples: `feat(frontend): move Trade Groups New button to left side`, `fix(tagging): allow groups across multiple accounts`.

### Pull Request Description

When opening or updating pull requests, include the following write-up in the PR body.

- Summary (required). Less than 100 words. What changed and why (not a file list)
- Features (optional). Bullet list of new behavior/capabilities, or "N/A".
- Refactoring (optional). Explain what changed and why. Describe new code structure and patterns.
- Fixes (optional). Bullet list of bugs corrected/remediation, or "N/A".
- Documentation (required if behavior changed)
- Additional notes (when applicable). Link issue(s) or external resources.

### UI Change Screenshots (optional)

A PR that changes the frontend UI may include a screenshot of the net result, captured with the built-in **demo data** (no live backend required). Not required — add one when a picture makes the change easier to review.

**Demo mode.** Enable with the `?demo=1` URL query param (e.g. `/positions?demo=1`) or `VITE_DEMO_MODE=1` in `frontend/.env`. When on, `frontend/src/lib/demoApi.ts` intercepts `fetch` and answers every backend call from the fixtures in `frontend/src/lib/demoData.ts` — so all pages render without a backend and components need no demo-specific code. A "DEMO MODE" banner is shown so screenshots are unambiguous.

**Capturing.** With the dev server running (`task frontend`):

```bash
cd frontend
node scripts/screenshot.mjs "/positions?demo=1" ../docs/screenshots/<name>.png [width] [height]
```

The script uses a preinstalled Chromium (Playwright's browser CDN is blocked by the web egress policy — do **not** run `playwright install`). Commit the image under `docs/screenshots/` and embed it in the PR body via its raw URL on the PR branch.

**Extending coverage.** If a changed view reads an endpoint the demo doesn't cover yet, add a fixture to `demoData.ts` and a route to `routeGet` (or a write handler) in `demoApi.ts` so the screenshot shows real content. Reuse the component/API types in fixtures so they can't drift.
