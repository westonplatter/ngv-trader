---
title: "feat: First-class realized P&L on trades and executions"
type: feat
status: proposed
created: 2026-03-14
artifact_contract: ce-unified-plan/v1
artifact_readiness: draft
product_contract_source: migrated-spec
execution: code
depth: standard
---

# feat: First-class realized P&L on trades and executions

> **Implementation status (verified 2026-10-10): not implemented.** Realized P&L
> is computed on read from `trade_executions.raw` by
> `execution_realized_pnl` in `src/services/execution_pnl.py` (TWS
> `commissionReport.realizedPNL` or FlexQuery `fifoPnlRealized`) and summed by
> `_trade_realized_pnl_from_executions` in `src/api/routers/trades.py`. Response
> schemas already expose `realized_pnl`. Neither `trades` nor `trade_executions`
> has a column. The read-only `v_execution_facts` / `v_trade_facts` views
> (migration `20260626140000_semantic_fact_views.py`) answer the SQL-reporting
> need for the semantic layer but add no columns.

## Goal Capsule

- **Objective:** `realized_pnl` becomes a stored column on `trade_executions` and `trades`, populated at sync time, so reads and SQL stop reparsing JSON.
- **Authority hierarchy:** The broker value in `raw` stays the audit source. The columns are derived state owned by the sync path, never operator-editable.
- **Execution profile:** Migration → sync write path → aggregate recompute → backfill → validate → switch reads.
- **Stop conditions:** Stop before cutting reads over if backfilled values disagree with the current read-path results for any sampled trade.
- **Tail ownership:** Standard repo flow; `task migrate`, `task test`, PR.

---

## Product Contract

### Summary

Add nullable `realized_pnl NUMERIC(18, 6)` to both tables. Sync parses it once per fill; `_recompute_trade_aggregates` sums it with the existing canonical and combo rules; APIs read the columns.

### Problem Frame

- Realized P&L lives only in `raw`, so SQL reporting, filtering, and indexing are harder than they should be.
- Aggregation is duplicated in the read path instead of the sync path that already owns other trade aggregates (quantity, average price, timestamps).

### Requirements

- R1. Each canonical execution exposes `realized_pnl` from a column.
- R2. `trades.realized_pnl` equals the sum of non-null canonical execution values: only canonical `combo_summary` rows when the trade has any, otherwise all canonical rows.
- R3. A broker `0` is stored as `0`; a missing broker value is `null`. If no canonical execution has a value, the trade is `null`.
- R4. Re-running sync over the same window does not duplicate or overcount.
- R5. Historical rows with parseable raw payloads are backfilled.
- R6. The trades page and execution details show the same values as today, with no operator-visible change.
- R7. After validation, APIs read the columns with no permanent raw-JSON fallback.

### Non-Goals

- Redefining how IBKR computes realized P&L.
- New realized/unrealized reporting endpoints.
- Backfill from sources other than stored raw payloads.

---

## Planning Contract

### Key Technical Decisions

KTD1. **Backfill is an Alembic data migration, not a standalone script.** The original spec called for a Python backfill script. Repo rules now require every DB state change, backfills included, to be a migration run via `task migrate`. The migration must be idempotent.

KTD2. **Reuse `execution_realized_pnl` as the single parser.** It already handles both TWS and FlexQuery shapes. The sync write path, backfill, and any remaining read code all call it.

KTD3. **Aggregate inside `_recompute_trade_aggregates`** (`src/services/sync_common.py`), shared by both sync paths, so the combo-summary safeguard lives in one place.

### Assumptions

- IBKR often reports realized P&L only on closing fills; consumers must not expect non-null on every row.

---

## Implementation Units

### U1. Schema

**Requirements:** R1

**Files:** `alembic/versions/` (new), `src/models.py` (`Trade`, `TradeExecution`)

**Approach:** Add the two nullable columns. No other schema changes.

### U2. Sync write path

**Requirements:** R1, R3, R4

**Files:** `src/services/trade_sync_flexquery.py`, `src/services/trade_sync_tws.py`

**Approach:** Populate `trade_executions.realized_pnl` via KTD2 when normalizing each fill. Keep `raw` unchanged.

### U3. Aggregate recompute

**Requirements:** R2, R3, R4

**Files:** `src/services/sync_common.py`

**Approach:** Per KTD3, sum per R2 and R3.

**Test scenarios:**

- Combo trade sums only `combo_summary` rows, not legs.
- Broker `0` is included; `null` rows are skipped; all-null gives `null`.
- Correction revisions: only canonical rows count.
- Re-sync is idempotent.

### U4. Backfill migration

**Requirements:** R5

**Approach:** Per KTD1. Populate execution values from `raw`, then trade values using the same aggregate rules. Safe to re-run.

### U5. Validate and switch reads

**Requirements:** R6, R7

**Files:** `src/api/routers/trades.py`

**Approach:** Compare stored values against the current read-path results for sampled executions and trades. Once they match, read the columns and remove `_trade_realized_pnl_from_executions` and the raw parsing from the response path.

---

## Verification Contract

| Gate          | Command                          | Applies to |
| ------------- | -------------------------------- | ---------- |
| Migration     | `task migrate ENV=dev`           | U1, U4     |
| Imports       | `uv run python scripts/check.py` | all        |
| Backend tests | `task test -- -k trade`          | U2, U3, U5 |

Not command-shaped: stored vs. computed comparison across a real sync window before U5 cutover.

---

## Definition of Done

- `trade_executions` and `trades` expose `realized_pnl` without app code parsing `raw`.
- Trade values match canonical execution sums with the combo safeguard.
- Re-running `trades.sync` does not overcount.
- Historical parseable rows are backfilled; `0` stays `0`; missing stays `null`.
- APIs read the stored columns in the normal path.

---

## Risks & Dependencies

- Combo double-counting if legs and combo summaries are both summed.
- Historical payloads may be unparseable, leaving partial backfill.
- Rollback is simple while columns are nullable and `raw` is untouched.

---

## Open Questions

- Should reports and the `v_*_facts` views move to the new columns in this change or a follow-up?

---

## Sources & Research

- `src/services/execution_pnl.py`, `src/api/routers/trades.py`, `src/services/sync_common.py`.
- `alembic/versions/20260626140000_semantic_fact_views.py`.
- `docs/trades-and-executions-sync.md`.
- Migrated from `docs/spec-first-class-realized-pnl-on-trades.md`.
