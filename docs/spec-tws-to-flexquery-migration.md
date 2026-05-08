# Spec: TWS to FlexQuery Trade and Position Data Migration

## Complexity: 4

Cross-cutting change that replaces the primary data ingestion path for trades and positions, requires schema migrations, logic rewrites in the sync services, and introduces a new sync-tracking table. The core database schema (trades, trade_executions, positions) is preserved but augmented.

## Purpose

The TWS (Trader WorkStation) API only exposes the last 7 days of execution history. This makes it impossible to reconstruct full trade lineage, backfill historical P&L, or audit multi-week strategies. FlexQuery is IBKR's batch reporting system and supports up to 365 days of trade history per request. Migrating to FlexQuery as the primary data source for trades and positions unlocks historical analysis and eliminates the hard 7-day ceiling.

## Problem

- `ib.reqExecutions(ExecutionFilter)` with a 7-day lookback is the only mechanism to pull trade history from TWS. Any execution older than 7 days is invisible to the system.
- Onboarding a new account or recovering from a sync outage longer than 7 days results in permanent data gaps with no recovery path.
- TWS requires a live, authenticated connection to the IB Gateway or Trader WorkStation desktop app. FlexQuery uses token-authenticated HTTP and can run without a live session.
- There is already a `scripts/fetch_flex_trades.py` proof-of-concept that fetches FlexQuery data but does not persist it to the database.

## Scope

- Replace `trade_sync.py`'s TWS-based execution fetch with a FlexQuery-based equivalent
- Persist FlexQuery trade data to the existing `trades` and `trade_executions` tables
- Add a `flex_sync_log` table to track fetched date ranges and enable idempotent re-runs
- Perform a historical backfill of trade executions using FlexQuery date ranges
- Augment the `trade_executions`, `trades`, and `positions` tables with metadata columns needed for FlexQuery data (`data_source`, `flex_transaction_id`, `as_of_date`)
- Normalize the `side` field values from `BOT`/`SLD` (TWS convention) to `BUY`/`SELL` (FlexQuery convention) across existing records and all future ingestion
- Define a position sync strategy using FlexQuery's `open_positions_by_account_id()` output

## Non-goals

- Real-time or intraday position data (FlexQuery is T-1 / end-of-day only)
- Removing TWS connectivity from the application entirely (TWS may still be used for order placement and real-time option chain data)
- Replacing order sync (`order_sync.py`) — open order tracking is outside this spec
- Modifying trade group assignment logic or the P&L reporting queries
- Supporting FlexQuery date ranges longer than 365 days in a single request (chunking handles this)

## Current State

- `src/services/trade_sync.py` connects to TWS via `ib_insync`, calls `ib.reqExecutions(ExecutionFilter)` with a configurable lookback (default 7 days), and upserts into `trades` and `trade_executions` using `ib_exec_id` as the idempotency key.
- `src/services/position_sync.py` calls `ib.positions()` to get live account positions and upserts into `positions` using the `uq_account_id_con_id` constraint.
- `scripts/fetch_flex_trades.py` demonstrates FlexQuery fetching via `ngv_reports_ibkr.FlexClient` and `CustomFlexReport` but only prints a summary — it does not write to the database.
- `ngv_reports_ibkr` (v0.5.0) is already a declared dependency and provides `FlexClient`, `CustomFlexReport`, and a 72-column Pandera schema for validation.
- Trade matching uses a 3-tier cascade to assign executions to a parent `trades` row: (1) `(account_id, ib_perm_id)` if `permId > 0`, (2) `(account_id, order_ref)` if `order_ref` starts with `"ngtrader-"`, (3) composite fallback on `(account_id, ib_order_id, symbol, side, trade_date)`. This cascade affects the `trades` aggregate table only.
- Trade group tagging operates on `trade_executions` directly — the join chain is `trade_groups → trade_group_executions.trade_execution_id → trade_executions.id`. The idempotency key for execution upsert is `ib_exec_id`. `permId` is not part of the tagging join and is not required for trade group assignment, P&L reporting, or the timeline.
- The `side` field currently stores `"BOT"` and `"SLD"` as received from TWS.

## Desired Outcome

- Trade executions can be fetched for any date range up to 365 days without a live TWS connection
- A full historical backfill of all available IBKR trade history is persisted to `trade_executions`
- The `flex_sync_log` table shows which date ranges have been successfully fetched per account, making gaps visible
- Position data is updated from FlexQuery EOD snapshots, tagged with the `as_of_date` they represent
- All records from both TWS and FlexQuery carry a `data_source` tag for auditability
- The `side` field is normalized to `"BUY"` / `"SELL"` uniformly across all records

## UX Requirements

- The `/api/positions` endpoint continues to work; positions reflect the most recent EOD snapshot with the `as_of_date` visible in the response
- The `/api/trades/sync` job endpoint continues to work; it triggers a FlexQuery fetch for the configured lookback window
- If a FlexQuery token is expired or missing, the sync job fails with a clear error message in the job log rather than silently producing an empty result
- The trades and executions APIs expose `data_source` as a readable field on each record

## Functional Plan

1. **Add schema migrations (Alembic)**

   Generate each revision below with the Alembic CLI and chain them on top of the current head. Each migration must implement a working `downgrade()` that exactly reverses `upgrade()`. Apply in the order listed.

   **Generating a revision:**

   ```bash
   uv run alembic revision -m "<message>"
   ```

   - The CLI auto-stamps the new file with `down_revision` set to the current head, so revisions chain in the order generated. Generate one at a time and verify the chain with `uv run alembic history` before applying.
   - Do **not** use `--autogenerate` for these migrations — they include data-only changes (the `side` normalization) and CHECK constraints that autogenerate does not produce reliably. Hand-write the `upgrade()` / `downgrade()` bodies using `op.add_column`, `op.create_table`, `op.create_index`, `op.create_check_constraint`, and `op.execute` as appropriate.
   - Apply with `uv run alembic upgrade head`; roll back one step with `uv run alembic downgrade -1`.
   - Reference existing migrations for style and column shape: `alembic/versions/20260227000000_add_trades_and_trade_executions.py` and `alembic/versions/20260217221407_create_positions_table.py`.

   **Revisions to generate:**
   1. **`add_data_source_to_trades_executions_positions`** (additive, non-breaking)
      - Adds `data_source TEXT NOT NULL DEFAULT 'tws'` to `trades`, `trade_executions`, and `positions`
      - Existing rows pick up `'tws'` via the server default; no row rewrite needed
      - `downgrade()` drops the column from all three tables
   2. **`add_flex_transaction_id_to_trade_executions`** (additive)
      - Adds `flex_transaction_id BIGINT NULL` to `trade_executions`
      - Adds partial unique index `ix_trade_executions_flex_transaction_id` `WHERE flex_transaction_id IS NOT NULL` (second idempotency net; see Data Model)
      - `downgrade()` drops the index then the column

   3. **`add_as_of_date_to_positions`** (additive)
      - Adds `as_of_date DATE NULL` to `positions`
      - `downgrade()` drops the column

   4. **`create_flex_sync_log_table`** (additive)
      - Creates `flex_sync_log` per the Data Model section, including the `(account_id, start_date, end_date)` index
      - `status` column constrained to `('in_progress', 'success', 'error', 'partial')` via CHECK constraint
      - FK `account_id` → `accounts(id)` `ON DELETE RESTRICT`
      - `downgrade()` drops the table

2. **Normalize `side` values in existing data (Alembic, batched)**

   Generated as a separate revision (`normalize_side_bot_sld_to_buy_sell`) that runs after the additive migrations above and is paired with the code change in step 2b. Run order matters — see Rollout.

   2a. **Data migration revision** — batched UPDATEs to avoid full-table locks on hot tables: - `UPDATE trades SET side='BUY' WHERE side='BOT'` and `'SLD' → 'SELL'`, executed in batches of 5,000 rows via `WHERE id BETWEEN ... AND ...` loops in the migration body - Same for `trade_executions.side` - No CHECK constraint is added — TWS sync may continue to write `BOT`/`SLD` briefly until the code change in 2b lands, and a hard constraint would block it. The migration is re-runnable as a cleanup sweep if needed. - `downgrade()` reverses the value mapping (`'BUY' → 'BOT'`, `'SELL' → 'SLD'`) in batches

   2b. **Code change (not a migration)** — update `side` normalization in `trade_sync.py` to produce `BUY`/`SELL` going forward. May be deployed before, after, or alongside the data migration; concurrent operation is acceptable.

3. **Build `src/services/flex_trade_sync.py`**
   - Accepts `account_id`, `start_date`, `end_date` as parameters
   - Fetches FlexQuery XML via `FlexClient.fetch_flex_report()`
   - Parses into DataFrame via `CustomFlexReport.trades_by_account_id()`
   - Strips open/close qualifiers from `buySell` (e.g. `"BUY (O)"` → `"BUY"`)
   - Skips tier-1 perm_id matching (FlexQuery has no `permId`); uses `ibOrderID` for parent trade grouping
   - Upserts `trade_executions` idempotently on `ib_exec_id`; sets `data_source = 'flex'` and `flex_transaction_id`
   - Recomputes parent trade aggregates using the same canonical-execution logic as `trade_sync.py`
   - Sets `exec_role = 'standalone'` for all FlexQuery executions (no combo detection)
   - Writes a `flex_sync_log` record on completion with row counts and status

4. **Build `src/services/flex_position_sync.py`**
   - Fetches `open_positions_by_account_id()` from FlexQuery
   - Aggregates LOT-level rows into net (account, conid) positions before upsert
   - Preserves the `uq_account_id_con_id` constraint by grouping: `SUM(quantity)` for position, weighted average for `avg_cost`
   - Sets `data_source = 'flex'` and `as_of_date` on each row

5. **Wire new services to job system**
   - Add `JOB_TYPE_FLEX_TRADES_SYNC` and `JOB_TYPE_FLEX_POSITIONS_SYNC` job type constants
   - Add API endpoints `/api/trades/flex-sync` and `/api/positions/flex-sync` (or extend existing sync endpoints with a `source` parameter)
   - Preserve existing TWS-based sync jobs as a fallback during transition

6. **Historical backfill script**
   - `scripts/backfill_flex_trades.py`: backfills the last 180 calendar days by default (`--days 180`), computing `end_date = today` and `start_date = today - 180 days`
   - Iterates configured accounts sequentially (parallel fetches against the same FlexQuery token hit `RATE_LIMITED (1018)`)
   - Writes one `flex_sync_log` row per account per run
   - **Backfill mode flag** on `flex_trade_sync`: skip per-execution parent-trade aggregate recompute during ingest; run aggregate recompute once at the end grouped by `(account_id, ib_order_id, trade_date)` to avoid O(n²) churn on the `trades` table
   - TWS sync and FlexQuery backfill may run concurrently — both write through `ib_exec_id` upserts and converge to the same row set
   - Reads `flex_sync_log` to detect already-covered ranges; supports longer ranges via ≤365-day chunking for future use, but the 180-day default fits in one request
   - Designed for one-time operator run; idempotent (re-runnable without duplicating data)

## Data Model and State Changes

### New columns (additive migrations, non-breaking)

| Table              | Column                | Type            | Default | Notes                                                   |
| ------------------ | --------------------- | --------------- | ------- | ------------------------------------------------------- |
| `trades`           | `data_source`         | `TEXT NOT NULL` | `'tws'` | `'tws'` or `'flex'`                                     |
| `trade_executions` | `data_source`         | `TEXT NOT NULL` | `'tws'` | `'tws'` or `'flex'`                                     |
| `trade_executions` | `flex_transaction_id` | `BIGINT`        | NULL    | FlexQuery `transactionID`; nullable for TWS records     |
| `positions`        | `data_source`         | `TEXT NOT NULL` | `'tws'` | `'tws'` or `'flex'`                                     |
| `positions`        | `as_of_date`          | `DATE`          | NULL    | The T-1 business date the FlexQuery snapshot represents |

### New table: `flex_sync_log`

```
flex_sync_log
  id              SERIAL PRIMARY KEY
  account_id      INTEGER NOT NULL REFERENCES accounts(id)
  start_date      DATE NOT NULL
  end_date        DATE NOT NULL
  fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
  row_count       INTEGER
  status          TEXT NOT NULL  -- 'success' | 'error' | 'partial'
  error_message   TEXT
```

Index: `(account_id, start_date, end_date)` — used to detect coverage gaps.

### Field mapping: FlexQuery → internal columns

| FlexQuery field        | Internal column                        | Notes                                    |
| ---------------------- | -------------------------------------- | ---------------------------------------- |
| `ibExecID`             | `trade_executions.ib_exec_id`          | Primary idempotency key; unchanged       |
| `ibOrderID`            | `trade_executions.ib_order_id`         | Used for parent trade grouping           |
| `transactionID`        | `trade_executions.flex_transaction_id` | New column                               |
| `conid`                | `trade_executions.con_id`              | Direct match                             |
| `buySell` (normalized) | `trade_executions.side`                | Strip `(O)`/`(C)` qualifiers             |
| `quantity`             | `trade_executions.quantity`            | Direct match                             |
| `tradePrice`           | `trade_executions.price`               | Direct match                             |
| `dateTime`             | `trade_executions.executed_at`         | TZ-aware datetime                        |
| `ibCommission`         | `trade_executions.commission`          | Inline; no async CommissionReport needed |
| `orderReference`       | `trade_executions.order_ref`           | Direct match                             |
| `accountId`            | resolved to `accounts.id`              | Via account lookup                       |

### `ib_perm_id` contract

FlexQuery does not provide `permId`. For FlexQuery-sourced `trades` rows, `ib_perm_id` will be NULL. The partial unique index `ix_trades_account_perm_id` is defined `WHERE ib_perm_id > 0`, so NULL rows do not violate the constraint. Parent trade deduplication for FlexQuery data relies on `ib_order_id` grouping within a calendar day.

### `exec_role` contract

All FlexQuery-sourced executions will have `exec_role = 'standalone'`. The `combo_summary` / `leg` split is a TWS-only artifact. Any reporting query that filters `exec_role != 'combo_summary'` must be audited to ensure it does not unintentionally exclude `standalone` flex records.

## API / Worker / Service Changes

- `GET /api/positions` — add `data_source` and `as_of_date` fields to `PositionResponse`
- `GET /api/trades` — add `data_source` to response
- `GET /api/trades/executions` — add `data_source` to response
- `POST /api/trades/sync` — remains; continues to call TWS sync during transition period
- `POST /api/positions/sync` — remains; continues to call TWS sync during transition period
- New job constants `JOB_TYPE_FLEX_TRADES_SYNC` and `JOB_TYPE_FLEX_POSITIONS_SYNC` added to worker
- `IB_JSON` environment variable must include `flex_token` and appropriate FlexQuery `query_id` values per account (already used by `fetch_flex_trades.py`)

## Operational Considerations

- FlexQuery tokens expire every 6 hours; the sync service must surface `FlexTokenExpiredError` as a job failure with a clear log message
- `FlexClient` already implements exponential backoff and handles `SERVER_BUSY` (1009) and `RATE_LIMITED` (1018) error codes — no new retry logic needed
- FlexQuery requests for large date ranges (e.g., 6 months) can return large XML payloads; memory usage should be monitored during backfill
- The backfill script should be run off-hours and is expected to take multiple minutes per account per year of history
- `flex_sync_log` rows are append-only for auditability; re-runs of the same date range create new log rows rather than updating existing ones

## Risks

- **Missing `permId` affects parent trade aggregation only.** FlexQuery has no `permId`, so `ib_perm_id` will be NULL on FlexQuery-sourced `trades` rows and tier-1 matching always fails. Trade group assignments, P&L reports, and the timeline are unaffected — they operate on `trade_executions` directly via `ib_exec_id`, which FlexQuery does provide. The risk is limited to parent trade grouping in the `trades` table: fallback to `ibOrderID` is session-scoped and could theoretically produce incorrect rollups if `ibOrderID` repeats across sessions. Mitigate by auditing `ibOrderID` uniqueness in a sample FlexQuery export before cutover.
- **LOT aggregation for positions may differ from TWS net position.** TWS returns the broker's computed net position. FlexQuery LOT aggregation is computed client-side by summing lots. If IBKR's internal lot assignment differs from a simple quantity sum, the positions will diverge. Validate by comparing FlexQuery-computed positions against TWS positions for a known account on a known date before disabling TWS position sync.
- **`buySell` qualifier variants are undocumented.** IBKR's FlexQuery documentation does not exhaustively list all `buySell` values. `"BUY (O)"`, `"SELL (C)"` are known; others may exist (e.g., partial fills, exercises). The normalization function must log and preserve any unrecognized values rather than silently dropping them.
- **Historical data coverage.** FlexQuery's 365-day window per request means history older than 1 year requires multiple chunked requests. IBKR retains data for up to 7 years, but the practical coverage limit depends on account age and query configuration.

## Observability

- Log `flex_sync_log` writes at INFO level: `[flex_trade_sync] account={id} start={date} end={date} rows={n} status=success`
- Log FlexQuery token errors at ERROR level with the IBKR error code
- Emit job-level metadata: rows fetched, rows inserted (new), rows skipped (duplicate), duration
- `flex_sync_log` table is the primary audit surface — operators can query it to see coverage gaps per account
- Add a `/api/admin/flex-sync-log` endpoint (or expose via the existing jobs API) for visibility

## Rollout

1. Apply additive Alembic migrations (`data_source`, `flex_transaction_id` + partial unique index, `as_of_date`, `flex_sync_log`) — no behavior change
2. Deploy code change in `trade_sync.py` to write `BUY`/`SELL` instead of `BOT`/`SLD`, and apply `normalize_side_bot_sld_to_buy_sell` — order is not strict; a brief overlap where TWS sync still writes `BOT`/`SLD` is acceptable and will be cleaned up on the next run of the migration or a follow-up sweep
3. Build and test `flex_trade_sync.py` against a staging account with a small date range (7 days)
4. Validate: compare FlexQuery-sourced executions against TWS-sourced executions for the same window — `ib_exec_id` values should match exactly
5. Run 180-calendar-day backfill script per account (`scripts/backfill_flex_trades.py --days 180`)
6. Build and test `flex_position_sync.py`; validate aggregated position totals against TWS positions for a known date
7. Update API response schemas to expose `data_source` and `as_of_date`
8. Switch `JOB_TYPE_TRADES_SYNC` to call `flex_trade_sync` by default; leave TWS sync available as a fallback job type
9. Monitor `flex_sync_log` for errors and coverage gaps over the first two weeks

## Acceptance Criteria

- `trade_executions` rows fetched via FlexQuery have `data_source = 'flex'` and a non-NULL `flex_transaction_id`
- Re-running `flex_trade_sync` for the same date range produces zero new inserts (idempotent on `ib_exec_id`)
- `flex_sync_log` contains one row per completed sync run with correct `start_date`, `end_date`, and `row_count`
- `GET /api/trades/executions` returns `data_source` on each execution row
- `GET /api/positions` returns `as_of_date` and `data_source` on each position row
- FlexQuery-sourced trade executions appear correctly in `/api/reports/pnl/trade-groups` P&L calculations
- A FlexQuery token expiration produces a job failure with a log message containing the IBKR error code — not a silent empty result
- For any 7-day window, the set of `ib_exec_id` values from a FlexQuery fetch matches the set from a TWS fetch for the same account and window
- Backfill of the last 180 calendar days for a single account completes in one FlexQuery request and produces zero duplicate inserts on a subsequent re-run
- Backfill across all configured accounts writes exactly one `flex_sync_log` row per account with `status = 'success'` and a non-zero `row_count` (or `status = 'error'` with `error_message` populated on failure)

## Open Questions

- **Hybrid vs FlexQuery-only for positions** _(resolved: hybrid)_: Keep TWS position sync active alongside FlexQuery EOD sync. TWS provides real-time intraday accuracy; FlexQuery provides the T-1 EOD snapshot tagged with `as_of_date`. Both write to `positions` via `uq_account_id_con_id`; `data_source` distinguishes which writer last touched a row. Open sub-question: should the API return both views, or always prefer the freshest write? Default to freshest-write until traders ask otherwise.

- **FlexQuery query configuration** _(resolved)_: Verified against a sample local FlexQuery export (not committed; gitignored under `scripts/data/`) — all six required fields are present in the configured query: `ibExecID`, `transactionID`, `orderReference`, `ibCommission`, `openCloseIndicator`, `conid`. No reconfiguration needed before the sync service is built.

- **`exec_role` and combo spreads** _(deferred to implementation)_: Should multi-leg spreads be reconstructed from FlexQuery data by grouping legs that share an `ibOrderID` and have matching `openCloseIndicator` patterns? Or is `standalone` for all FlexQuery executions acceptable in the trade group P&L view? **The user has agency and responsibility to direct this decision during implementation.** No commitment is made in this spec; the implementing engineer should surface the tradeoff to the user when the FlexQuery sync service is being built and let the user choose based on what the trade group P&L view actually needs at that point.
  Use the same trade group contstruction logic if possible. If not, we'll need to find another leg matching mechanism.

## Related Files

- `src/services/trade_sync.py` — current TWS trade sync (reference for logic to port)
- `src/services/position_sync.py` — current TWS position sync (reference for logic to port)
- `scripts/fetch_flex_trades.py` — existing FlexQuery proof-of-concept (starting point for new service)
- `src/models.py` — all SQLAlchemy models; tables to be augmented
- `alembic/versions/20260227000000_add_trades_and_trade_executions.py` — migration reference for trades schema
- `alembic/versions/20260217221407_create_positions_table.py` — migration reference for positions schema
- `.venv/lib/python3.12/site-packages/ngv_reports_ibkr/flex_client.py` — FlexQuery HTTP client
- `.venv/lib/python3.12/site-packages/ngv_reports_ibkr/custom_flex_report.py` — DataFrame extraction methods
- `.venv/lib/python3.12/site-packages/ngv_reports_ibkr/schemas/ibkr_flex_report.py` — 72-column Pandera validation schema

## Task List

### Phase 1: Schema migrations (additive, non-breaking)

- [x] 1.1 Generate Alembic revision `add_data_source_to_trades_executions_positions` — `790b1dac7d8a`
- [x] 1.2 Generate Alembic revision `add_flex_transaction_id_to_trade_executions` — `1a9d2390bd8e`
- [x] 1.3 Generate Alembic revision `add_as_of_date_to_positions` — `6b5e1576ec39`
- [x] 1.4 Generate Alembic revision `create_flex_sync_log_table` — `01ca3f6d2394`
- [x] 1.5 Applied to prod — head advanced through `01ca3f6d2394`; existing rows correctly default-tagged `data_source='tws'`

### Phase 2: Side normalization

- [x] 2.1 Generate Alembic revision `normalize_side_bot_sld_to_buy_sell` — `683ce2f42f99` (batched 5k UPDATEs, reversible)
- [x] 2.2 Update `trade_sync.py` to write `BUY`/`SELL` (added `_normalize_side` helper)
- [x] 2.3 Applied to prod — verified: only `BUY`/`SELL` remain in `trades` and `trade_executions`; zero `BOT`/`SLD` records

### Phase 3: FlexQuery trade sync service

- [x] 3.1 Create `src/services/flex_trade_sync.py` with `sync_flex_trades(account_code, start_date, end_date, ...)` signature
- [x] 3.2 Wire `FlexClient.fetch_flex_report()` + `CustomFlexReport.trades_by_account_id()` parsing
- [x] 3.3 `_normalize_buy_sell` strips `(O)`/`(C)` qualifiers and logs unrecognized variants
- [x] 3.4 Field mapping per spec; `data_source='flex'`, `flex_transaction_id`, `exec_role='standalone'`
- [x] 3.5 `on_conflict_do_update` on `ib_exec_id`; `flex_transaction_id` partial unique provides second net
- [x] 3.6 `_resolve_or_create_flex_trade` skips tier-1 perm_id; `skip_aggregate_recompute` flag + `recompute_aggregates_for_trades` for backfill
- [x] 3.7 Writes `flex_sync_log` row (in_progress → success/error) with row_count and error_message
- [x] 3.8 `FlexTokenExpiredError` raised on token-related fetch failures; logged at ERROR with stored error_message

### Phase 4: FlexQuery position sync service

- [x] 4.1 Create `src/services/flex_position_sync.py`
- [x] 4.2 `_aggregate_lots`: SUM(quantity) + weighted-avg avg_cost grouped by `conid`
- [x] 4.3 Upsert via `uq_account_id_con_id`; sets `data_source='flex'`, `as_of_date` from `reportDate`
- [ ] 4.4 Validate aggregated totals against TWS positions for a known account/date — pending live data run

### Phase 5: Job system & API wiring

- [x] 5.1 `JOB_TYPE_FLEX_TRADES_SYNC` and `JOB_TYPE_FLEX_POSITIONS_SYNC` added; worker handlers wired in `scripts/work_jobs.py`
- [x] 5.2 `POST /api/v1/trades/flex-sync` and `POST /api/v1/positions/flex-sync` enqueue endpoints
- [x] 5.3 TWS sync endpoints/jobs preserved as fallback (untouched)
- [x] 5.4 `data_source` (+ `flex_transaction_id`) added to `TradeResponse`, `TradeExecutionResponse`, `TradeExecutionListItem`
- [x] 5.5 `data_source` and `as_of_date` added to `PositionResponse`
- [x] 5.6 `GET /api/v1/admin/flex-sync-log` in new `src/api/routers/admin.py` (filterable by `account_id`, default 100 most recent)

### Phase 6: Historical backfill

- [x] 6.1 `scripts/backfill_flex_trades.py` with `--days 180` default; sequential per-account from `IB_JSON`
- [x] 6.2 Calls `sync_flex_trades(skip_aggregate_recompute=True)` per chunk, then `recompute_aggregates_for_trades` once at the end
- [x] 6.3 Chunks ranges into ≤365-day windows via `_chunked_ranges`; each `flex_sync_log` row is per-chunk per-account
- [ ] 6.4 Verify idempotency (re-run produces zero new inserts) — partial: second backfill ran without duplicate-key errors; needs a clean re-run with explicit insert-count check

### Phase 6.5: Discovered during validation (not in original spec)

- [x] 6.5.1 Widen `ib_order_id` and `ib_perm_id` from `INTEGER` to `BIGINT` on `trades` and `trade_executions` (migration `22ce4113fb3c`) — IBKR order IDs are 10-digit values that overflow 32-bit int
- [x] 6.5.2 Make `_execution_realized_pnl` source-agnostic — reads `raw.commissionReport.realizedPNL` (TWS) **or** `raw.fifoPnlRealized` (FlexQuery)
- [x] 6.5.3 Refactor backfill + worker to fetch FlexQuery once per token and dispatch over `report.account_ids()` — a single FlexQuery token returns trades for all linked accounts; the IB_JSON `name` field is a local token alias, not the IBKR account ID
- [x] 6.5.4 `previous_business_day()` helper — defaults `end_date` to last weekday (skips Sat/Sun; no holiday calendar)
- [x] 6.5.5 Cleaned up an `accounts` row created by the early alias-as-account bug, plus its orphan `flex_sync_log` rows

### Phase 7: Validation, rollout, observability

- [ ] 7.1 Validate `ib_exec_id` parity between FlexQuery and TWS for an overlapping 7-day window — flex executions are now in DB across multiple accounts; needs the parity query against the matching TWS window
- [x] 7.2 Logging in place: `[flex_trade_sync] account=… start=… end=… rows=… status=success` at INFO; token errors at ERROR with stored `flex_sync_log.error_message`; metrics dict returns `fetched_executions_count`, `inserted_executions_count`, `canonical_changes_count`, `touched_trades_count`
- [x] 7.3 Audit complete — no `exec_role != 'combo_summary'` filters exist anywhere; the three `exec_role` reads (`trade_groups.py:512`, `trades.py:215`, `trades.py:677`) all handle `standalone` correctly. P&L reports (`reports.py`) do not filter on `exec_role`
- [ ] 7.4 Switch `JOB_TYPE_TRADES_SYNC` default to `flex_trade_sync` — **deferred (user decision)**; both endpoints currently coexist
- [ ] 7.5 Run 180-day backfill per account; monitor `flex_sync_log` for two weeks — pending live run
- [ ] 7.6 Verify all Acceptance Criteria pass — needs a clean idempotent backfill + position validation

### Open decision (to surface during Phase 3)

- [ ] Decide combo-spread reconstruction strategy for FlexQuery executions (reuse trade group construction logic if possible; otherwise propose alternative leg-matching mechanism) — surface tradeoff to user before finalizing `flex_trade_sync.py`
