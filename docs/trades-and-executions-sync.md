# Trades and Executions Sync

## Purpose

Describe the production data model and sync behavior for ingesting IBKR trades
with fill-level fidelity, correction handling, and idempotent re-runs.

## Model overview

- `trade_executions` is the source of truth.
- `trades` is a derived parent aggregate over canonical executions.
- All execution rows are stored with broker identifiers and `raw` payload for audit.

## Key identity rules

Execution identity:

- Uniqueness is keyed by `ib_exec_id`.
- IBKR correction revisions are grouped by `(account_id, exec_id_base)`.
- Highest revision is `is_canonical=true`; older revisions remain stored as history.

Trade parent matching (in priority order):

1. `(account_id, ib_perm_id)` when `ib_perm_id > 0`.
2. `(account_id, order_ref)` when `order_ref` exists.
3. Fallback composite: `(account_id, ib_order_id, symbol, side, trade_date_utc)`.

Notes:

- `order_ref` is not globally unique in IBKR tooling.
- `ngtrader-*` refs are the only refs treated as intentional unique keys.

## Sync behavior

The sync service should:

1. Fetch executions for the lookback window.
2. Normalize and upsert `trade_executions` idempotently.
3. Recompute canonical revision flags by `exec_id_base`.
4. Resolve/create parent `trades` rows by matching rules.
5. Recompute parent aggregates from canonical executions only.

Expected properties:

- Safe to re-run with the same window.
- Append/update semantics; no destructive history deletes.
- Metrics returned for fetched/inserted/updated/canonical-changed/touched-trades.

## Spread-specific handling

For BAG/combo executions:

- Parent spread quantity/price comes from canonical combo-summary executions.
- Leg executions remain persisted for detail, commission, and audit.

For individually legged spreads (no BAG parent):

- Build suggestions from shared `ib_order_id` or spread-tagged `order_ref`.
- Require operator confirmation before writing linked combo records.
- Avoid timestamp-proximity auto-linking to reduce false positives.

## Job and API surface

Worker/job:

- Job type: `trades.sync`.
- Worker handler runs the sync and supports payload overrides
  (`host`, `port`, `client_id`, `connect_timeout_seconds`, `lookback_days`).
- Post-order processing should enqueue both `positions.sync` and `trades.sync`.

Read API:

- `GET /api/v1/trades`
- `GET /api/v1/trades/{trade_id}`
- `GET /api/v1/trades/{trade_id}/executions`

## Acceptance checklist

- Re-running sync with the same window does not duplicate executions.
- Exactly one canonical execution per `(account_id, exec_id_base)`.
- Parent `trades` totals match canonical execution aggregates.
- Spread suggestions require explicit operator confirm/dismiss actions.

## Related docs

- `spec-trades-and-executions-sync.md` for detailed implementation spec
- `spreads-across-orders-trades-executions.md` for combo/spread behavior across layers
- `client-portal-combo-spreads.md` for CPAPI-native combo position linkage
