# NextGenTrader

This is a agentic project enabling one person to operate as an quick and nimble trading desk.

## Docs Index Rule

If any `docs/*.md` file is added, modified, renamed, or deleted (excluding `docs/_index.md`), update `docs/_index.md` in the same change.

`docs/_index.md` has two sections — place the entry in the right one:

- **Project Docs** — runbooks, how-tos, and reference material.
- **Specs** — architecture specs and design proposals (files prefixed `spec-`).

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
- `frontend/`: React + Vite UI for portfolio/positions views.
- `docs/`: runbooks and architecture notes.
- `Taskfile.yaml`: common dev commands for API, frontend, and migrations.

### Primitives

- `src/db.py`: pure-ish DB URL and SQLAlchemy engine builders (`get_database_url`, `get_engine`).
- `src/utils/ibkr_account.py`: account masking helper (`mask_ibkr_account`) for safer logs.
- `scripts/execute_cl_buy_or_sell_continous_market.py`: contains many small parsing/formatting primitives (`parse_float`, `parse_contract_expiry`, `format_money`) used by the order workflow.

### Components

- `src/models.py`: SQLAlchemy `Base` and `Position` entity (single source for table structure in app code).
- `src/schemas.py`: Pandera DataFrame schema for position validation shape.
- `src/api/deps.py`: FastAPI DB session dependency component (`get_db`).
- `src/api/routers/positions.py`: API component that maps DB `Position` rows to response model and exposes `/positions`.
- `frontend/src/components/PositionsTable.tsx`: UI component fetching and rendering `/api/v1/positions`.

### Services

- `scripts/setup_db.py`: service entrypoint to create DB (if needed) and run Alembic migrations.
- `scripts/download_positions.py`: service entrypoint to connect to IBKR TWS and upsert live positions into Postgres.
- `scripts/execute_cl_buy_or_sell_continous_market.py`: trade execution service for CL front-month market orders with confirmation + what-if checks.
- `scripts/test_tws_connection.py`: connectivity/health service for IBKR API session checks.
- `src/api/main.py`: FastAPI service entrypoint (`task api` or `uv run uvicorn src.api.main:app --reload --port 8000`).
- `frontend/` dev server: UI service (`task frontend` or `npm run dev` in `frontend/`).

### End-to-End Workflow (Current)

1. Start IBKR TWS or Gateway.
2. Run `scripts/setup_db.py` to ensure DB + migrations are current.
3. Run `scripts/download_positions.py` to ingest broker positions.
4. Run backend API (`src/api/main.py`) and frontend (`frontend/`).
5. Use `scripts/execute_cl_buy_or_sell_continous_market.py` for live order execution.

### Key Files By Concern

- Broker integration: `scripts/download_positions.py`, `scripts/test_tws_connection.py`, `scripts/execute_cl_buy_or_sell_continous_market.py`
- Data model/storage: `src/models.py`, `src/db.py`, `alembic/versions/20260217221407_create_positions_table.py`
- API surface: `src/api/main.py`, `src/api/routers/positions.py`
- UI surface: `frontend/src/App.tsx`, `frontend/src/components/PositionsTable.tsx`
- Ops docs: `docs/download-positions.md`, `docs/execute-future-cl-order-script.md`, `docs/secrets-using-1password.md`

### Active Architecture Direction

- Planned migration to installable internal app package layout: `docs/spec-installable-internal-app-layout.md`.
- Target state is `src/ngtrader/...` imports (replacing `from src...`) while staying installable via uv.
