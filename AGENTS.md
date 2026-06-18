# NextGenTrader

Agentic software enabling one person to operate as an quick and nimble quantative futures, vol. and options trade desk.

## Docs Index Rule

If any `docs/*.md` file is added, modified, renamed, or deleted (excluding `docs/_index.md`), update `docs/_index.md` in the same change.

`docs/_index.md` separates **current-state docs** (how the system works today, grouped by area) from **open specs** (`spec-*` files, proposed or in-progress). Place each entry in the right place. Every `spec-*.md` carries a status banner at the top (e.g. `Status: NOT IMPLEMENTED` / `PARTIAL`).

When a spec ships, do the wrap-up in the same change:

1. Rewrite it to describe the system as it works today, or fold it into the relevant current-state doc.
2. If kept as a standalone file, remove the `spec-` prefix; if folded, delete the spec file.
3. Move/remove its `docs/_index.md` entry accordingly (out of the open-specs table into the right current-state section).
4. Update any in-repo references to the old filename.

When writing documentation or summaries, default to high-level overviews that point to detailed resources rather than verbose step-by-step instructions. Avoid hardcoding filenames in docs when the user wants lightweight guidance.

## Task Delegation

Do NOT make changes beyond what was explicitly requested. Do not proactively remove, move, or restructure columns, fields, or UI elements unless specifically asked. When in doubt, do less.

## Code Validation

Always use `uv run python scripts/check.py <module>` to verify imports. Never use `uv run python -c` for import checks.

- All modules: `uv run python scripts/check.py`
- Specific: `uv run python scripts/check.py src.services.jobs`

Exits 1 on failure.

## Codebase Survey

### Repository Layout

- `src/`: Python backend application code (current import root is `src`).
- `scripts/`: operator-facing workflows and broker/database utilities.
- `alembic/` + `alembic.ini`: database migrations for Postgres schema.
- `frontend/`: React + Vite UI (positions, orders, trades, tagging, pricing, tradebot chat).
- `docs/`: current-state docs and specs; see `docs/_index.md`.
- `Taskfile.yaml`: common dev commands for API, frontend, and migrations.

### Primitives

- `src/db.py`: DB URL and SQLAlchemy engine builders (`get_database_url`, `get_engine`).
- `src/utils/ibkr_account.py`: account masking helper (`mask_ibkr_account`) for safer logs.
- `src/utils/contract_display.py`: human-readable contract labels (`contract_display_name`).
- `src/utils/env_vars.py`: typed env-var helpers.
- `src/services/sync_common.py`: shared sync helpers (id parsing, account upsert, canonical flags, aggregates).

### Components

- `src/models.py`: SQLAlchemy `Base` plus all entities (single source for table structure). Beyond `Position`: `ContractRef`, `Account`, `Order`/`OrderEvent`, `Job`, `Trade`/`TradeExecution`, `FlexSyncLog`, `TradeGroup*`/`Tag*` (tagging), `WatchList*`, market-data `LatestFutures*`/`TsFutures*`, `OptionChainMeta`, `SavedStructure`, `UserPreference`, `WorkerHeartbeat`.
- `src/schemas.py`: Pandera DataFrame schema for positions validation shape.
- `src/api/deps.py`: FastAPI DB session dependency (`get_db`).
- `src/api/routers/*.py`: REST surface — `positions`, `orders`, `trades`, `futures` (market data), `jobs`, `workers`, `events` (SSE), `tradebot` (chat), `watch_lists`, `tags`, `trade_groups`, `accounts`, `structures`, `reports`, `admin`, `user_preferences`.
- `frontend/src/components/*.tsx`: React UI (positions, orders, trades, tagging, pricing, tradebot chat) consuming `/api/v1/*`.

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

- Current import root is `src` (`from src...`). A previously-planned migration to an installable `src/ngtrader/...` package layout has no active spec on disk; re-add one under `docs/spec-*.md` before resuming that work.

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

## Pull Requests

### Pull Request Description

When opening or updating pull requests, include the following write-up in the PR body.

- Summary (required). Less than 100 words. What changed and why (not a file list)
- Features (optional). Bullet list of new behavior/capabilities, or "N/A".
- Refactoring (optional). Explain what changed and why. Describe new code structure and patterns.
- Fixes (optional). Bullet list of bugs corrected/remediation, or "N/A".
- Documentation (required if behavior changed)
- Additional notes (when applicable). Link issue(s) or external resources.
