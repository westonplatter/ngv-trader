---
topics: ["trades", "sync", "flexquery", "executions", "jobs"]
code_dirs_or_files:
  [
    "src/services/fill_ingest.py",
    "src/services/trade_sync_flexquery.py",
    "src/services/trade_sync_tws.py",
    "src/services/sync_common.py",
    "src/services/flex_client_factory.py",
    "src/api/routers/trades.py",
  ]
description: IBKR trade ingestion with fill-level fidelity — FlexQuery vs dormant TWS paths, execution identity and corrections, deterministic combo handling, two-phase Flex jobs, and token pause and retry.
---

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

Both are adapters over one ingest, `src/services/fill_ingest.py`. Each transport
normalizes its rows into `NormalizedFill`s (`flex_rows_to_fills`,
`tws_fills_to_fills`) and names its `FillSource`; `ingest_fills()` then resolves
parent trades, upserts `trade_executions`, synthesizes combo summaries, enforces
canonical flags, and recomputes parent aggregates. The `FillSource` carries the
two things that differ between transports: whether the composite parent match
uses the trade date, and whether legs are re-tagged after the loop. Lower-level
helpers (id parsing, account upsert, canonical flags, aggregates) live in
`src/services/sync_common.py`; the Flex fetch and `FlexTokenExpiredError` in
`src/services/flex_client_factory.py`.

> Separately, the **intraday TWS overlay** writes today's fills to its own
> `live_executions` table (not `trade_executions`) for live realized P&L. Settled
> FlexQuery stays canonical: live fills are deduped/purged by `ib_exec_id` once
> they settle. See [core/intraday-tws-overlay.md](intraday-tws-overlay.md).

## Model overview

- `trade_executions` is the source of truth (one row per fill).
- `trades` is a derived parent aggregate over canonical executions.
- Every execution stores broker identifiers plus the full `raw` payload for audit.

### Key columns on `trade_executions`

| Column                | Purpose                                                                                                             |
| --------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `ib_exec_id`          | Unique fill identity (idempotency key)                                                                              |
| `flex_transaction_id` | BIGINT fallback id for Flex BookTrade rows (assignments/exercises/expirations) that lack an execID; idempotency net |
| `data_source`         | `'flex'` or `'tws'`                                                                                                 |
| `sec_type`            | Contract secType (`FUT`, `FOP`, `BAG`, …)                                                                           |
| `con_id`              | IB contract id; joins to `contracts` (`ContractRef`) for leg enrichment                                             |
| `exec_role`           | `standalone` \| `leg` \| `combo_summary` — drives spread aggregation                                                |
| `is_canonical`        | Highest revision wins; older correction revisions retained as history                                               |

`ib_perm_id` and `ib_order_id` are `BIGINT` (IBKR perm ids exceed 32-bit range).

## Identity and correction rules

Execution identity:

- Uniqueness is keyed by `ib_exec_id`.
- IBKR correction revisions are grouped by `(account_id, exec_id_base)`.
- The highest revision is `is_canonical=true`; older revisions remain as history.
  Enforced by `_enforce_canonical_flags()` in `sync_common.py`.

Trade parent matching (priority order), one implementation in
`fill_ingest.resolve_parent_trade()`. A tier that applies but finds nothing creates
the trade; it does not fall through:

1. `(account_id, ib_perm_id)` when `ib_perm_id > 0`. FlexQuery has no `permId`, so
   its fills never reach this tier.
2. `(account_id, order_ref)` when `order_ref` starts with `ngtrader-`.
3. Fallback composite: `(account_id, ib_order_id, symbol, side)`. For TWS
   (`FillSource.composite_match_uses_trade_date`) the candidate must also share the
   fill's derived `YYYY-MM-DD` trade date, because TWS order ids are per session and
   repeat across days. FlexQuery's `ibOrderID` is unique, and a date check there
   only produced duplicate parents at timezone boundaries, so it is off.

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

FlexQuery has no native combo-summary row, so the adapter tags each leg with its
`brokerageOrderID` (`NormalizedFill.combo_key`) and the ingest **synthesizes** one
summary per combo: quantity is the gcd of the leg sizes, price the net cash per
unit, and the `ib_exec_id` is the legs' reserved `.01` slot when they share a
prefix, else `"{brokerage_order_id}.combo"`. A group only counts as a combo when
it spans two or more distinct conids, so partial fills of one contract are never
summarized. TWS receives a native BAG fill (`NormalizedFill.is_combo_summary`)
and the ingest re-tags sibling legs in a post-insert pass
(`FillSource.retag_legs_after_ingest`) to handle late-arriving combos.

The unsettled intraday path applies the same `exec_role` vocabulary to
`live_executions`, grouping by broker order key instead of `brokerageOrderID`;
see [core/intraday-tws-overlay.md](intraday-tws-overlay.md).

FlexQuery's `Open/CloseIndicator` is the authoritative Action (Open/Close) and
the only source of the **Expired** action. Unsettled rows have neither — TWS
does not stamp fills with cover-vs-add — so they show a derived best-effort
Action that this indicator supersedes at settlement.

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

- `trades.sync.flexquery` → `handle_trades_sync_flexquery` (active). An
  entrypoint, not a fetch: it queues one `trades.flexquery.initiate_request`
  per active token. Positions follow the identical three-job shape.
- `trades.flexquery.initiate_request` → sends the request, gets a reference
  code, and schedules the collection after a window-scaled wait (20s up to a
  week, 60s to a month, 120s to a quarter, 180s beyond).
- `trades.flexquery.fetch_report` → collects that reference code and syncs.
  Re-checks every 30s while the statement is still building, up to 20 checks.
- `trades.sync.tws` → `handle_trades_sync_tws` (dormant, unregistered)
- Flex payload options: `days`, `start_date`/`end_date`, `account_code`,
  `token_id`. (`lookback_days` is the _TWS_ handler's field — the Flex handler
  ignores it and falls back to a 7-day default.)
  Credentials are **not** payload-supplied — by default every active row in
  `flexquery_tokens` is used, decrypted with `FLEX_TOKEN_ENCRYPTION_KEY`. See
  [getting-started.md](../getting-started.md#flexquery-tokens).
- `token_id` narrows a run to one `flexquery_tokens.id` (the primary key, so a
  queued job survives a rename). Use it for backfills so a token that is
  erroring or rate-limited is not dragged through every job in the series.

### Token pause window

`1025: Too many failed attempts` means IBKR has cooled a token off, and it is
earned almost entirely by repeated **SendRequest** calls. On a 1025 the token's
`paused_until` is set 20 minutes out with a `pause_reason`; while it holds,
**both** phases defer for that token rather than calling IBKR. The Accounts UI
shows the countdown and offers Pause / Resume.

Gating both phases matters: a send that ignores the pause earns a fresh 1025 and
re-pauses from _then_, so an unchecked sender slides the cooldown forward
indefinitely and the token never recovers.

Splitting the fetch is what keeps this rare: one SendRequest per window, with
the waiting done between jobs rather than inside a blocked worker slot.

### Retry cadence

Applies to the in-process client retries that remain (the TWS paths and any
direct `fetch_flex_report` caller); the two-phase job flow waits between jobs
instead.

IBKR takes longer to build a statement the wider the window, answering
`1001: Statement could not be generated at this time` while it works. Retrying a
month-wide pull on the one-week cadence exhausts the attempt budget before the
statement is ready — and enough wasted attempts earns a `1025: Too many failed
attempts` lockout that outlives the job.

`src/services/flex_client_factory.py` is the single place every sync path builds
its client, and it scales retry delays with the requested span: unchanged at or
under 7 days, then linearly (`span / 7`), capped at 6x. A 7-day window keeps its
~8-minute budget across 10 attempts; a monthly backfill gets ~35 minutes.

Read API (`src/api/routers/trades.py`):

- `GET /api/v1/trades`
- `GET /api/v1/trades/{trade_id}`
- `GET /api/v1/trades/{trade_id}/executions`
- `GET /api/v1/trade-executions` — flat, filterable execution list across trades
  (also surfaces unsettled live TWS fills; see [core/intraday-tws-overlay.md](intraday-tws-overlay.md)).
- `POST /api/v1/trades/sync/flex-query` — accepts a fixed lookback (`days`),
  an explicit `start_date`/`end_date`, or `since_last_trade: true` (derives the
  window from the latest execution date across all accounts through the
  previous business day; the response echoes the computed `start_date`/`end_date`).
- `POST /api/v1/trades/sync/tws` — enqueues `trades.sync.tws`, which has no
  registered handler (see "dormant, unregistered" above); the job stays queued.

Responses expose `data_source`, `flex_transaction_id`, `sec_type`, `exec_role`.
Realized PnL is currently computed on read from `raw` (see
[the first-class realized P&L plan](../plans/2026-03-14-001-feat-first-class-realized-pnl-plan.md)
for the proposal to persist it as first-class columns).

## Acceptance properties

- Re-running sync with the same window does not duplicate executions.
- Exactly one canonical execution per `(account_id, exec_id_base)`.
- Parent `trades` totals match canonical execution aggregates.
- Combo parent totals come from `combo_summary` fills, not summed legs.

## Key files

- `src/services/fill_ingest.py` (the shared ingest)
- `src/services/trade_sync_flexquery.py`, `src/services/trade_sync_tws.py` (adapters)
- `src/services/sync_common.py`
- `tests/test_trade_sync_flexquery.py`, `tests/test_trade_sync_tws.py`
- `src/services/flex_client_factory.py`
- `src/models.py` (`Trade`, `TradeExecution`, `FlexSyncLog`)
- `src/api/routers/trades.py`
- Migrations: `20260227000000_add_trades_and_trade_executions`,
  `20260227120000_add_spread_fields_to_trade_executions`,
  `20260507204206_add_data_source_*`, `20260507204209_add_flex_transaction_id_*`,
  `20260507204210_create_flex_sync_log_table`,
  `20260507212131_widen_ib_order_id_and_ib_perm_id_*`,
  `20260513080943_rename_job_type_tws_flexquery`
