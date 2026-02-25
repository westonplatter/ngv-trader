# Download IBKR Positions to Postgres

Pull live positions from TWS/IB Gateway and store them in the `positions` table.

## Prereqs

- Postgres is running on `DB_HOST:DB_PORT` (defaults to `localhost:5432`)
- TWS or IB Gateway is running
- `.env.dev` has `BROKER_TWS_PORT`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`

## First-time setup

Create the database and run migrations:

```bash
op run --env-file=.env.dev -- uv run python scripts/setup_db.py --env dev
```

This connects to the `postgres` maintenance DB, creates `ngtrader_dev` if needed, and runs `alembic upgrade head`.

## Download positions

```bash
op run --env-file=.env.dev -- uv run python scripts/download_positions.py --env dev
```

- Connects to TWS (clientId=2) and calls `ib.positions()`
- Gets or creates an `Account` row for each unique IBKR account string
- Upserts each position into the `positions` table (keyed on `account_id` + `con_id`)
- Prints a summary of positions saved

## Accounts and aliases

IBKR account IDs (e.g., "DU1234567") are sensitive and should not be visible during screencasting. The `accounts` table stores the raw account string internally and exposes a user-settable `alias` instead.

- **`accounts` table** — `id` (PK), `account` (raw IBKR string, unique), `alias` (nullable)
- **`positions.account_id`** — plain integer referencing `accounts.id` (no FK constraint, keeps test fixtures simple)
- **Default display** — when `alias` is NULL, the API returns `"Account Alias {id}"` (e.g., "Account Alias 1")
- **Custom alias** — set via `PATCH /api/v1/accounts/{id}` with `{"alias": "My Paper Account"}`, or through the Accounts page in the frontend
- **Raw account string** is never exposed through the API

## Verify

```bash
psql -d ngtrader_dev -c "SELECT p.account_id, a.alias, p.symbol, p.sec_type, p.position, p.avg_cost, p.fetched_at FROM positions p JOIN accounts a ON p.account_id = a.id;"
```

## Key files

| File                            | Purpose                                           |
| ------------------------------- | ------------------------------------------------- |
| `src/db.py`                     | Builds SQLAlchemy engine from env vars            |
| `src/models.py`                 | `Account` and `Position` SQLAlchemy models        |
| `src/schemas.py`                | Pandera schema for positions DataFrame validation |
| `scripts/setup_db.py`           | Creates DB + runs migrations                      |
| `scripts/download_positions.py` | Pulls positions from TWS, saves to DB             |
| `alembic/`                      | Migration files (Rails-style datetime naming)     |
