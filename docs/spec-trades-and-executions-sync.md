# Spec: Trades and Executions Sync

## Purpose

Add broker trade ingestion with fill-level fidelity, idempotency, and correction handling.

## Scope

- New DB model for `trades` (parent) and `trade_executions` (child).
- New IBKR sync service and job type for trades/executions.
- Read API endpoints for operator visibility.
- Worker wiring and post-order sync triggers.

## Non-goals

- Strategy/risk logic.
- Multi-broker abstraction.
- PnL analytics beyond fields needed for raw trade storage.

## Design Principles

- `trade_executions` is the source of truth.
- Parent `trades` rows are derived aggregates over executions.
- All sync writes must be idempotent.
- Corrections must not duplicate effective fills.
- Keep operator auditability: preserve raw broker identifiers.

## Canonical Data Model

### `trades`

Recommended columns:

- `id` (pk)
- `account_id` (int, not null)
- `ib_perm_id` (int, nullable)
- `order_ref` (text, nullable)
- `ib_order_id` (int, nullable)
- `client_id` (int, nullable)
- `symbol`, `sec_type`, `side`, `exchange`, `currency` (nullable text as needed)
- `status` (text, not null; e.g. `partial`, `filled`, `cancelled`, `unknown`)
- `total_quantity` (float, not null, default `0`)
- `avg_price` (float, nullable)
- `first_executed_at`, `last_executed_at` (timestamptz, nullable)
- `fetched_at` (timestamptz, not null)
- `created_at`, `updated_at` (timestamptz, not null)

Indexes/constraints:

- Partial unique index on `(account_id, ib_perm_id)` where `ib_perm_id > 0`.
- Optional unique index on `(account_id, order_ref)` where `order_ref is not null`.
- Non-unique index on `(account_id, last_executed_at desc)`.

### `trade_executions`

Recommended columns:

- `id` (pk)
- `trade_id` (int, not null)
- `account_id` (int, not null; denormalized for conflict/index performance)
- `ib_exec_id` (text, not null)
- `exec_id_base` (text, not null; `ib_exec_id` without correction suffix)
- `exec_revision` (int, not null, default `0`)
- `ib_perm_id` (int, nullable)
- `ib_order_id` (int, nullable)
- `order_ref` (text, nullable)
- `client_id` (int, nullable)
- `executed_at` (timestamptz, not null)
- `quantity`, `price` (float, not null)
- `side` (text, nullable)
- `exchange`, `currency`, `liquidity` (nullable text)
- `commission` (float, nullable)
- `is_canonical` (bool, not null, default `true`)
- `raw` (jsonb, not null)
- `fetched_at` (timestamptz, not null)
- `created_at`, `updated_at` (timestamptz, not null)

Indexes/constraints:

- Unique `(account_id, ib_exec_id)`.
- Index on `(account_id, exec_id_base, exec_revision desc)`.
- Index on `(trade_id, executed_at)`.

## Identity and Matching Rules

### Primary execution identity

- Use unique `(account_id, ib_exec_id)` for ingestion idempotency.

### Correction handling

- Parse `ib_exec_id` into:
  - `exec_id_base` (stable part)
  - `exec_revision` (suffix revision, default `0`)
- For all rows with same `(account_id, exec_id_base)`:
  - mark highest revision as `is_canonical = true`
  - mark lower revisions as `is_canonical = false`
- Trade aggregates use only canonical rows.

### Trade parent identity

Parent resolution order per incoming execution:

1. If `ib_perm_id > 0`: match/create by `(account_id, ib_perm_id)`.
2. Else if `order_ref` exists: match/create by `(account_id, order_ref)`.
3. Else fallback to stronger composite:
   - `(account_id, client_id, ib_order_id, symbol, side, trade_date)`
   - where `trade_date` is execution date in UTC (not a coarse time bucket).

## Sync Service Plan

Add `src/services/trade_sync.py`:

- `check_trades_tables_ready(engine)`:
  - verify `trades`, `trade_executions`, `accounts`.
- `sync_trades_once(engine, host, port, client_id, connect_timeout_seconds, lookback_days)`:
  - connect TWS/Gateway
  - fetch executions/fills for lookback window
  - normalize records into execution DTOs
  - upsert into `trade_executions`
  - enforce canonical revision flags by `exec_id_base`
  - resolve/create parent `trades` rows via matching rules
  - recompute affected parent aggregates from canonical executions only
  - return metrics:
    - `fetched_executions_count`
    - `inserted_executions_count`
    - `updated_executions_count`
    - `canonical_changes_count`
    - `touched_trades_count`
    - `window_start`, `window_end`

Behavior:

- Append/update semantics only; do not delete history on sync.
- Safe to re-run repeatedly with same window.

## Jobs and Workers

### New job type

- Add `JOB_TYPE_TRADES_SYNC = "trades.sync"` in `src/services/jobs.py`.

### Jobs worker handler

- In `scripts/work_jobs.py`:
  - map `trades.sync` -> `handle_trades_sync`.
  - parse payload overrides:
    - `host`, `port`, `client_id`, `connect_timeout_seconds`, `lookback_days`.

### Triggering

- Keep manual enqueue path available via API/tooling.
- After `worker:orders` processes one or more orders, enqueue:
  - `positions.sync` (existing behavior)
  - `trades.sync` (new behavior, idempotent enqueue).

## API Plan

Add `src/api/routers/trades.py`:

- `GET /api/v1/trades`
  - filters: `account_id`, `status`, `symbol`, `limit`.
- `GET /api/v1/trades/{trade_id}`
- `GET /api/v1/trades/{trade_id}/executions`
  - include `is_canonical`, `ib_exec_id`, `exec_id_base`, `exec_revision`.

Mount in `src/api/main.py`.

## Tradebot Tooling Plan

Optional but recommended:

- Add read tool `list_trades` for operator chat context.
- Add side-effect tool `enqueue_trades_sync_job`.
- Keep existing order-submit confirmation guard unchanged.

## Migration Plan

Single Alembic revision:

1. Create `trades`.
2. Create `trade_executions`.
3. Add indexes/constraints (including partial unique indexes).
4. No destructive changes to existing `orders`, `order_events`, `positions`.

## Rollout Sequence

1. Migration + ORM models.
2. Trade sync service.
3. `trades.sync` job type + worker handler.
4. API router for read access.
5. Optional Tradebot tools.
6. Optional frontend trades table.
7. Operational validation with repeated sync runs.

## Acceptance Criteria

- Re-running `trades.sync` with same window does not duplicate executions.
- Multiple executions for one trade are stored and queryable.
- Corrected executions produce one canonical execution per `exec_id_base`.
- `trades` aggregates match canonical execution totals.
- `ib_perm_id > 0` rows are unique by `(account_id, ib_perm_id)`.
- `ib_perm_id = 0` rows resolve via `order_ref` or composite fallback.
- Post-order flow can refresh both positions and trades via jobs.

## Risks and Mitigations

- IB execution windows vary by TWS/Gateway config.
  - Mitigation: configurable `lookback_days`, default conservative backfill.
- Missing `order_ref` on older/manual orders.
  - Mitigation: composite fallback including `client_id`.
- Correction suffix format variance.
  - Mitigation: parser with safe default (`revision=0`) + raw capture for audit.
