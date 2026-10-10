---
topics: ["architecture", "onboarding", "agents"]
code_dirs_or_files: ["src/", "scripts/", "frontend/", "alembic/", "tests/"]
description: Repository layout, primitives, components, services, and key files by concern — the orientation map for agents and new contributors.
---

# Codebase Map

Orientation for an agent or contributor landing in the repo. For the runtime
architecture diagram and setup steps, see [getting-started.md](../getting-started.md).
For domain vocabulary, see [CONCEPTS.md](../../CONCEPTS.md).

## Repository layout

- `src/`: Python backend application code (current import root is `src`).
- `scripts/`: operator-facing workflows and broker/database utilities.
- `alembic/` + `alembic.ini`: database migrations for Postgres schema.
- `frontend/`: React + Vite UI (positions, orders, trades, strategies, pricing, tradebot chat).
- `docs/`: current-state docs and specs; see the [docs index](../README.md).
- `docs/solutions/`: documented solutions to past problems (bugs, best practices, workflow patterns), organized by category with YAML front matter (`module`, `tags`, `problem_type`) — relevant when implementing or debugging in documented areas.
- `docs/plans/`: dated planning artifacts; historical, not current-state.
- `CONCEPTS.md`: shared domain vocabulary (entities, named processes, status concepts).
- `tests/`: pytest suite run via `task test` against a dedicated `ngv_trader_test` database.
- `Taskfile.yaml`: common dev commands for API, frontend, migrations, and tests.

## Primitives

- `src/db.py`: DB URL and SQLAlchemy engine builders (`get_database_url`, `get_engine`).
- `src/utils/ibkr_account.py`: account masking helper (`mask_ibkr_account`) for safer logs.
- `src/utils/contract_display.py`: human-readable contract labels (`contract_display_name`).
- `src/utils/env_vars.py`: typed env-var helpers.
- `src/services/sync_common.py`: shared sync helpers (id parsing, account upsert, canonical flags, aggregates).

## Components

- `src/models.py`: SQLAlchemy `Base` plus all entities (single source for table structure). Beyond `Position`: `ContractRef`, `ActivatedProduct`, `Account`, `Order`/`OrderEvent`, `Job`, `Trade`/`TradeExecution`, `FlexSyncLog`, `TradeGroup*`/`Tag*` (tagging), `WatchList*`, market-data `LatestFutures*`/`TsFutures*`, `OptionChainMeta`, `SavedStructure`, `UserPreference`, `WorkerHeartbeat`, intraday overlay `LivePosition`/`LatestQuote`/`LiveExecution`/`LatestOptionMetrics`.
- `src/schemas.py`: Pandera DataFrame schema for positions validation shape.
- `src/api/deps.py`: FastAPI DB session dependency (`get_db`).
- `src/api/routers/*.py`: REST surface — `positions`, `orders`, `trades`, `futures` (market data), `activated_products`, `jobs`, `workers`, `events` (SSE), `tradebot` (chat), `watch_lists`, `tags`, `trade_groups`, `accounts`, `structures`, `reports`, `admin`, `user_preferences`, `flexquery_tokens`.
- `frontend/src/components/*.tsx`: React UI (positions, orders, trades, strategies, pricing, tradebot chat) consuming `/api/v1/*`.

## Services

- `worker:jobs` (`scripts/work_jobs.py` shim → `src/workers/jobs.py`): background job handlers — FlexQuery trade/position sync, market data, contracts, watchlists, order fetch. Queue primitive `src/services/jobs.py`.
- `worker:orders` (`scripts/work_order_queue.py`): order-lifecycle scaffold; **submission is disabled** (see [workers.md](../workers.md)).
- Sync services: `src/services/{trade,position}_sync_flexquery.py` (active), `..._tws.py` (dormant), `contract_sync.py`, `market_data.py`.
- `src/services/tradebot_agent.py`: LangGraph chat agent (DB reads + job enqueue; no `ib_async` import).
- Operator utilities: `scripts/setup_db.py` (DB + migrations), `scripts/download_positions.py` (one-time TWS position bootstrap), `scripts/fetch_flex_trades.py`, `scripts/test_tws_connection.py`, `scripts/validate_env.py`.
- `src/api/main.py`: FastAPI entrypoint (`task api` or `uv run uvicorn src.api.main:app --reload --port 8000`).
- `frontend/` dev server: UI service (`task frontend` or `bun run dev` in `frontend/`).

## End-to-end workflow (current)

1. Run `scripts/setup_db.py` to ensure DB + migrations are current.
2. (Optional) Start IBKR TWS/Gateway and run `scripts/download_positions.py` for a one-time position bootstrap.
3. Run backend API (`src/api/main.py`) and frontend (`frontend/`).
4. Run `worker:jobs` for ongoing sync; trades/positions sync via FlexQuery (no local broker session required).

## Key files by concern

- Broker integration: `src/services/{trade,position}_sync_flexquery.py`, `src/services/flex_client_factory.py`, `src/services/contract_sync.py`, `scripts/fetch_flex_trades.py`, `scripts/test_tws_connection.py`
- Data model/storage: `src/models.py`, `src/db.py`, `alembic/versions/`
- API surface: `src/api/main.py`, `src/api/routers/`
- UI surface: `frontend/src/App.tsx`, `frontend/src/components/`
- Workers/jobs: `src/workers/jobs.py`, `src/services/jobs.py`, `scripts/work_jobs.py`, `scripts/work_order_queue.py`
- Ops docs: [getting-started.md](../getting-started.md), [workers.md](../workers.md), [trades-and-executions-sync.md](../trades-and-executions-sync.md), [secrets-using-1password.md](../secrets-using-1password.md)

## Active architecture direction

- Current import root is `src` (`from src...`). A previously-planned migration to an installable `src/ngv_trader/...` package layout has no active spec on disk; re-add one under `docs/spec-*.md` before resuming that work.
