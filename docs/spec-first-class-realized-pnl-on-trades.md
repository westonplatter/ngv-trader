# Spec: First-Class Realized PnL on Trades

## Purpose

Make IBKR realized PnL a first-class field on both `trade_executions` and `trades` so execution-level PnL is queryable in SQL and trade-level PnL is available without reparsing JSON on every read.

## Problem

- Realized PnL currently arrives from IBKR in the commission report and is preserved only inside `trade_executions.raw`.
- The API reparses `raw["commissionReport"]["realizedPNL"]` on read instead of using schema-backed fields.
- This makes SQL reporting, filtering, indexing, and downstream rollups harder than necessary.
- The current approach also duplicates aggregation logic in the read path instead of the sync path that already owns other trade aggregates.

## Scope

- Add a nullable `realized_pnl` column to `trade_executions`.
- Add a nullable `realized_pnl` column to `trades`.
- Update trade sync to persist execution-level realized PnL from IBKR and recompute trade-level realized PnL from canonical executions.
- Update trade read APIs to use the stored columns instead of reparsing JSON for normal responses.

## Non-goals

- Rework how IBKR defines realized PnL or override broker semantics.
- Add new realized/unrealized PnL reporting endpoints in this phase.
- Backfill historical realized PnL from sources other than existing stored raw commission-report payloads.

## Current State

- `src/services/trade_sync.py` stores `commissionReport.realizedPNL` only inside `trade_executions.raw`.
- `src/api/routers/trades.py` extracts execution-level realized PnL from raw JSON and sums it for trade-level responses.
- `trade_executions` is the source of truth for fills and correction revisions.
- `trades` is already a derived aggregate over canonical executions for quantity, average price, and execution timestamps.
- Combo/spread trades already require special aggregation handling so combo summary fills are used instead of double-counting legs.

## Desired Outcome

- Each canonical execution can expose a schema-backed `realized_pnl` value directly from the database.
- Each trade row stores a schema-backed `realized_pnl` aggregate recomputed during sync with the same canonical and combo rules used elsewhere.
- Trade APIs return realized PnL without reparsing JSON in the normal read path.
- Raw broker payloads remain stored for audit and debugging.

## UX Requirements

- The trades page should continue to show trade-level realized PnL with no behavior change for operators.
- Trade execution details should continue to show execution-level realized PnL, now sourced from a first-class column.
- If IBKR omits realized PnL for an execution, the API should return `null` rather than guessing a value.

## Functional Plan

1. Add first-class realized PnL columns.
   - Add nullable `realized_pnl` to `trade_executions`.
   - Add nullable `realized_pnl` to `trades`.
2. Persist execution-level realized PnL during trade sync.
   - Parse `commissionReport.realizedPNL` once when normalizing each fill.
   - Continue storing the original commission report in `raw` for audit fidelity.
3. Recompute trade-level realized PnL in the aggregate recomputation path.
   - Use canonical executions only.
   - If a trade has `combo_summary` executions, sum only canonical `combo_summary.realized_pnl` values.
   - Otherwise sum all canonical execution `realized_pnl` values.
   - Ignore canonical executions where `realized_pnl` is `null`.
   - Treat broker `0` as a real value and include it in the sum.
   - If no canonical execution has a non-null realized PnL, set `trades.realized_pnl` to `null`.
4. Simplify the read path.
   - Return execution `realized_pnl` from `trade_executions.realized_pnl`.
   - Return trade `realized_pnl` from `trades.realized_pnl`.
   - After backfill and validation, switch API reads fully to the stored columns with no permanent raw-JSON fallback.

## Data Model and State Changes

- `trade_executions.realized_pnl NUMERIC(18, 6) NULL`
- `trades.realized_pnl NUMERIC(18, 6) NULL`
- Existing `raw.commissionReport.realizedPNL` remains unchanged.
- Trade aggregate recomputation must treat `trades.realized_pnl` as derived state owned by the sync path, not an operator-editable field.
- An Alembic migration should add both nullable columns only.
- A Python backfill script should populate existing data after the schema change:
  - `trade_executions.realized_pnl` from stored `raw.commissionReport.realizedPNL` when parseable
  - `trades.realized_pnl` by reusing the canonical execution aggregate logic already owned by the sync path
- The backfill script must be idempotent and safe to re-run.

## API / Worker / Service Changes

- `src/services/trade_sync.py`
  - persist `trade_executions.realized_pnl`
  - recompute `trades.realized_pnl` inside `_recompute_trade_aggregates`
- `src/api/routers/trades.py`
  - read realized PnL from schema-backed columns
  - remove JSON parsing helpers once rollout no longer needs fallback behavior
- No new endpoints are required.
- Existing `trades.sync` worker/job flow remains the owner of aggregate recomputation.

## Operational Considerations

- Sync remains idempotent because execution identity and canonical revision behavior do not change.
- Correction handling must continue to prevent duplicate effective realized PnL by aggregating canonical executions only.
- Historical backfill should run through a Python script after the migration so existing trades page responses do not depend on a fresh sync before showing realized PnL.
- Rollback is straightforward if raw payloads remain untouched and new columns are nullable.
- Cutover should happen only after backfill validation confirms stored values match expected execution-level and trade-level results.

## Risks

- IBKR realized PnL may appear only on closing executions, so consumers must not assume non-null values on all fills.
- Combo trades can be double-counted if leg executions and combo summary executions are both included in trade-level aggregation.
- Historical raw payloads may contain unparseable or missing realized PnL values, resulting in partial backfill.

## Observability

- Trade sync logs should include whether realized PnL fields were parsed and stored for fetched executions.
- Aggregate recomputation should make it easy to inspect touched trades where `realized_pnl` becomes `null` or changes unexpectedly.
- Validation should include comparing stored columns against raw commission-report payloads for sample executions.

## Rollout

1. Add an Alembic migration for both nullable `NUMERIC(18, 6)` columns.
2. Update ORM models and trade sync write path.
3. Update aggregate recomputation to populate `trades.realized_pnl`.
4. Run an idempotent Python backfill script to populate historical execution and trade rows.
5. Validate stored values against raw commission-report payloads and recomputed trade sums.
6. Switch trade APIs to read the stored columns with no permanent fallback.

## Acceptance Criteria

- `trade_executions` rows expose `realized_pnl` directly without needing to parse `raw` in application code.
- `trades.realized_pnl` matches the sum of non-null canonical execution-level realized PnL using the existing combo-summary safeguard.
- Re-running `trades.sync` with the same window does not duplicate or overcount realized PnL.
- Existing trades and executions with parseable historical commission-report payloads are backfilled by the Python script.
- Broker `0` realized PnL values are preserved as `0`, not coerced to `null`.
- Trade and execution API responses continue to return `null` when IBKR did not provide realized PnL.
- After validation, trade and execution APIs read realized PnL from stored columns without reparsing raw JSON in the normal response path.

## Open Questions

- Whether reports should move immediately to the new `realized_pnl` columns in this phase or follow in a separate change.

## Related Files

- `src/services/trade_sync.py`
- `src/api/routers/trades.py`
- `src/models.py`
- `alembic/versions/20260227000000_add_trades_and_trade_executions.py`
- `docs/trades-and-executions-sync.md`
