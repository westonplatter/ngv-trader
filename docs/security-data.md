# Security Data

Current-state documentation for how ngtrader stores and serves futures and futures-options market data.

## Purpose

The system keeps contract metadata and market data in Postgres so the app can:

1. read futures term structure from the DB
2. read futures options chains and vol-surface inputs from the DB
3. support pre-trade snapshots without direct frontend-to-IBKR calls

The current implementation is futures-focused. The main paths in use are for `FUT` and `FOP` contracts.

## Main Components

### Contract metadata

Contract definitions live in `contracts` via `ContractRef`.

Important fields:

1. `con_id`
2. `symbol`
3. `sec_type`
4. `contract_month`
5. `contract_expiry`
6. `strike`
7. `right`
8. `trading_class`
9. `underlying_con_id`

`underlying_con_id` captures the parent relationship used by the futures options data flow:

1. root `IND` rows have no parent
2. `FUT` rows point at the root index contract
3. `FOP` rows point at the underlying futures contract

This relationship is populated during contract-chain sync and is used later by market-data jobs and API filters.

### Latest snapshot tables

Hot-path reads use one-row-per-contract snapshot tables:

1. `latest_futures`
2. `latest_futures_options`

These tables are the default source for API reads.

### Time-series history tables

Append-only history is stored in:

1. `ts_futures`
2. `ts_futures_options`

These tables are used for historical lookups such as `as_of` futures reads.

## Data Model

### `latest_futures`

Stores the newest known futures snapshot per `con_id`.

Fields:

1. bid / ask / last / close
2. volume / open_interest
3. `market_ts`
4. `ingested_at`
5. `updated_at`

### `ts_futures`

Stores append-only futures history.

Fields:

1. bid / ask / last / close
2. volume / open_interest
3. `market_ts`
4. `ingested_at`

Indexes:

1. `(con_id, market_ts)`
2. `(market_ts)`

### `latest_futures_options`

Stores the newest known futures-options snapshot per `con_id`.

Fields:

1. bid / ask / last / close
2. volume / open_interest
3. `iv`
4. `delta`
5. `gamma`
6. `theta`
7. `vega`
8. `und_price`
9. `market_ts`
10. `ingested_at`
11. `updated_at`

### `ts_futures_options`

Stores append-only futures-options history.

Fields mirror `latest_futures_options` except there is no `updated_at`.

Indexes:

1. `(con_id, market_ts)`
2. `(market_ts)`

## Write Path

Market data is fetched by background jobs, not directly by API routes.

Relevant job handlers in `scripts/work_jobs.py`:

1. `market_data.futures_prices`
2. `market_data.futures_options`
3. `market_data.snapshot`

These call service functions in `src/services/market_data.py`.

### Futures price writes

`fetch_futures_prices(...)`:

1. selects active front-month `FUT` contracts from `contracts`
2. requests snapshot tickers from IBKR in batches
3. appends one row per contract to `ts_futures`
4. upserts one row per contract into `latest_futures`

The upsert is guarded by `market_ts` so an older snapshot does not overwrite a newer one.

### Futures options writes

`fetch_futures_options(...)`:

1. selects active `FOP` contracts from `contracts`
2. optionally filters by `underlying_con_id`, strike bounds, right, DTE, and modulus
3. requests snapshot tickers from IBKR in batches
4. reads `modelGreeks` when available
5. falls back to `latest_futures` for `und_price` when IBKR does not supply it
6. appends one row per contract to `ts_futures_options`
7. upserts one row per contract into `latest_futures_options`

As with futures, the upsert is guarded by `market_ts`.

### Snapshot writes

`fetch_snapshot(...)` is the targeted path for a specific set of contract IDs.

Behavior:

1. loads the requested contracts from `contracts`
2. requests IBKR snapshot tickers
3. writes futures rows into `ts_futures` / `latest_futures`
4. writes futures-options rows into `ts_futures_options` / `latest_futures_options`

This is used when the app wants fresh quotes for a narrow set of instruments instead of a broader chain refresh.

## Read Path

The API reads from Postgres only.

Main router:

1. `src/api/routers/futures.py`

### `GET /api/v1/futures/{symbol}/term-structure`

Default behavior:

1. reads active `FUT` contracts from `contracts`
2. left joins `latest_futures`
3. returns front contracts ordered by `contract_expiry`

Historical behavior:

1. if `as_of` is provided, the route reads from `ts_futures`
2. it picks the latest row per `con_id` with `market_ts <= as_of`

Returned data includes:

1. contract metadata
2. bid / ask / last / close
3. volume / open_interest
4. `observed_at`
5. computed `dte`

### `GET /api/v1/futures/{symbol}/options`

Reads active `FOP` contracts from `contracts` and left joins `latest_futures_options`.

Supported filters:

1. `underlying_con_id`
2. `underlying_month`
3. `strike_gte`
4. `strike_lte`
5. `right`
6. `dte_gte`
7. `dte_lte`

Returned data includes:

1. contract metadata
2. bid / ask / last
3. `iv`
4. `delta`
5. `gamma`
6. `theta`
7. `vega`
8. `und_price`
9. `observed_at`

### `GET /api/v1/futures/{symbol}/vol-surface`

Uses the same base query as the options endpoint and returns option rows intended for vol-surface views.

Additional filters:

1. `expiry_start`
2. `expiry_end`

### `GET /api/v1/futures/{symbol}/option-filter`

Returns effective option-filter values for a symbol.

Behavior:

1. loads static symbol config from `src.data.option_filters`
2. reads the front futures price from `latest_futures`
3. computes strike bounds using config plus the current futures price
4. rounds bounds to modulus when configured

This is a helper endpoint for UI and workflow logic that needs strike-range defaults derived from current DB prices.

## Contract Sync Dependency

The market-data layer depends on contract metadata already being present.

In practice the normal sequence is:

1. sync contracts and contract chains
2. fetch futures prices
3. fetch futures-options prices
4. read the data through futures endpoints or targeted snapshots

`contract_sync.py` also uses `latest_futures` as an input for moneyness-based option filtering.

## Operational Notes

### IBKR boundary

The backend API does not fetch market data directly from the browser request path. Workers talk to IBKR and write DB snapshots. API routes then read from the DB.

### Batching

Market data requests are fetched in batches in `src/services/market_data.py`. The current batch size is `100`.

### Delayed data fallback

The market-data service sets `reqMarketDataType(3)`, which requests delayed-frozen data when live data is unavailable.

### Missing greeks

If IBKR does not provide `modelGreeks` for a futures option:

1. the row is still written
2. greek fields remain null
3. a warning is logged

### Freshness semantics

`market_ts` is the freshness guard. New writes can append to history even if they are stale relative to the latest snapshot table, but the `latest_*` row is only replaced when the incoming `market_ts` is newer or equal.

## Current Limitations

1. The futures `as_of` path exists only for term-structure reads; options endpoints currently read from `latest_futures_options`.
2. The system is focused on futures and futures options, not a general securities market-data platform.
3. `market_ts` currently uses the fetch time used by the service, not an exchange-native timestamp from a separate market-data event log.
4. The storage design is Postgres-first and does not yet use TimescaleDB features.

## Related Files

1. `alembic/versions/20260306090000_add_security_data_tables.py`
2. `src/models.py`
3. `src/services/market_data.py`
4. `src/services/contract_sync.py`
5. `src/api/routers/futures.py`
6. `scripts/work_jobs.py`
