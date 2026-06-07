# Trades and Executions Sync

Current-state documentation for ingesting IBKR trades with fill-level fidelity,
correction handling, deterministic spread detection, and idempotent re-runs.

## Data sources: FlexQuery (primary) vs TWS (dormant)

Two ingestion paths exist. Both write the same tables and are distinguished by a
`data_source` column (`'flex'` or `'tws'`).

- **FlexQuery** is the active path. The worker fetches a hosted Flex report over
  HTTPS (no local broker session needed; data is T-1/delayed).
  Service: `src/services/trade_sync_flexquery.py`. Job: `trades.sync.flexquery`.
- **TWS** is dormant. The code exists but its handler is **not registered** in the
  worker dispatcher (`src/workers/jobs.py` `get_handler`). To re-enable, add
  `JOB_TYPE_TRADES_SYNC_TWS` back to the dispatch map.
  Service: `src/services/trade_sync_tws.py`. Job: `trades.sync.tws`.

Shared helpers (id parsing, account upsert, canonical flags, aggregates) live in
`src/services/sync_common.py`.

## Model overview

- `trade_executions` is the source of truth (one row per fill).
- `trades` is a derived parent aggregate over canonical executions.
- Every execution stores broker identifiers plus the full `raw` payload for audit.

### Key columns on `trade_executions`

| Column | Purpose |
| --- | --- |
| `ib_exec_id` | Unique fill identity (idempotency key) |
| `flex_transaction_id` | BIGINT fallback id for Flex BookTrade rows (assignments/exercises/expirations) that lack an execID; idempotency net |
| `data_source` | `'flex'` or `'tws'` |
| `sec_type` | Contract secType (`FUT`, `FOP`, `BAG`, …) |
| `con_id` | IB contract id; joins to `contracts` (`ContractRef`) for leg enrichment |
| `exec_role` | `standalone` \| `leg` \| `combo_summary` — drives spread aggregation |
| `is_canonical` | Highest revision wins; older correction revisions retained as history |

`ib_perm_id` and `ib_order_id` are `BIGINT` (IBKR perm ids exceed 32-bit range).

## Identity and correction rules

Execution identity:

- Uniqueness is keyed by `ib_exec_id`.
- IBKR correction revisions are grouped by `(account_id, exec_id_base)`.
- The highest revision is `is_canonical=true`; older revisions remain as history.
  Enforced by `_enforce_canonical_flags()` in `sync_common.py`.

Trade parent matching (priority order):

1. `(account_id, ib_perm_id)` when `ib_perm_id > 0`.
2. `(account_id, order_ref)` when `order_ref` exists.
3. Fallback composite: `(account_id, ib_order_id, symbol, side, trade_date_utc)`.

Notes:

- `order_ref` is not globally unique in IBKR tooling. Only `ngtrader-*` refs are
  treated as intentional unique keys.
- A partial unique index enforces `(account_id, ib_perm_id)` only when `ib_perm_id > 0`.

## Spread / combo handling (deterministic)

Spread detection is **explicit**, not heuristic. The old `commission == 0` guess is
gone. Roles are set during sync via `exec_role`:

- A BAG/combo fill is `combo_summary`; its underlying legs are `leg`; everything
  else is `standalone`.
- The parent `trades.sec_type` is set to `'BAG'` for combo trades.

Aggregation (`sync_common.py`): parent quantity/price come from `combo_summary`
fills when present, otherwise from all canonical non-leg fills. Leg fills are kept
for detail, commission, and audit but excluded from parent totals.

FlexQuery has no native combo-summary row, so the sync **synthesizes** one per
combo by grouping on `brokerageOrderID`, with a deterministic
`ib_exec_id = "{brokerage_order_id}.combo"`. TWS receives a native BAG fill and
re-tags sibling legs in a post-insert pass to handle late-arriving combos.

## Sync behavior

1. Fetch executions for the lookback window.
2. Normalize and upsert `trade_executions` idempotently on `ib_exec_id`.
3. Recompute canonical revision flags by `exec_id_base`.
4. Resolve/create parent `trades` rows by the matching rules above.
5. Recompute parent aggregates from canonical executions only.

Properties: safe to re-run with the same window; append/update only (no
destructive history deletes); returns metrics for
fetched/inserted/canonical-changed/touched-trades.

### `flex_sync_log`

Each Flex run writes a row to `flex_sync_log` (`account_id`, `start_date`,
`end_date`, `fetched_at`, `row_count`, `status`, `error_message`). Used for audit
and coverage-gap detection. Token failures raise `FlexTokenExpiredError` and are
recorded with `status='error'`. View via `GET /api/v1/admin/flex-sync-log`.

## Job and API surface

Worker/job (handled by `worker:jobs`, see [workers.md](workers.md)):

- `trades.sync.flexquery` → `handle_trades_sync_flexquery` (active)
- `trades.sync.tws` → `handle_trades_sync_tws` (dormant, unregistered)
- Flex payload overrides: `flex_token`, `query_id`, `lookback_days` (otherwise
  resolved from the `IB_JSON` secret; see [secrets-using-1password.md](secrets-using-1password.md)).

Read API (`src/api/routers/trades.py`):

- `GET /api/v1/trades`
- `GET /api/v1/trades/{trade_id}`
- `GET /api/v1/trades/{trade_id}/executions`
- `POST /api/v1/trades/sync/flex-query`

Responses expose `data_source`, `flex_transaction_id`, `sec_type`, `exec_role`.
Realized PnL is currently computed on read from `raw` (see
[spec-first-class-realized-pnl-on-trades.md](spec-first-class-realized-pnl-on-trades.md)
for the proposal to persist it as first-class columns).

## Acceptance properties

- Re-running sync with the same window does not duplicate executions.
- Exactly one canonical execution per `(account_id, exec_id_base)`.
- Parent `trades` totals match canonical execution aggregates.
- Combo parent totals come from `combo_summary` fills, not summed legs.

## Key files

- `src/services/trade_sync_flexquery.py`, `src/services/trade_sync_tws.py`
- `src/services/sync_common.py`
- `src/services/flex_client_factory.py`
- `src/models.py` (`Trade`, `TradeExecution`, `FlexSyncLog`)
- `src/api/routers/trades.py`
- Migrations: `20260227000000_add_trades_and_trade_executions`,
  `20260227120000_add_spread_fields_to_trade_executions`,
  `20260507204206_add_data_source_*`, `20260507204209_add_flex_transaction_id_*`,
  `20260507204210_create_flex_sync_log_table`,
  `20260507212131_widen_ib_order_id_and_ib_perm_id_*`,
  `20260513080943_rename_job_type_tws_flexquery`
