# Spec: First-Class Spread Fields on Trades and Executions

## Purpose

Replace heuristic-based spread detection (commission=0) with explicit,
schema-enforced fields so combo/spread trades are deterministically identified
at both the execution and trade level.

## Problem

Current spread detection relies on a runtime heuristic: "if some canonical
executions have commission=0 and others have commission>0, the zero-commission
fills are combo summaries." This works in practice but is:

- **Fragile** — depends on IBKR always setting commission=0 on combo fills.
- **Implicit** — every aggregation query must re-derive whether a trade is
  a spread.
- **Not queryable** — cannot filter or index on "show me all spread trades"
  without scanning executions.

## Scope

Add three new columns to `trade_executions` and update ingestion + aggregation
to use them. No new columns on `trades` — combo detection uses the existing
`trades.sec_type = 'BAG'` (set from the combo fill's contract during sync).

## Changes

### 1. Add `sec_type` and `con_id` to `trade_executions`

Store the execution's contract `secType` and `conId` on each row.

```sql
trade_executions.sec_type  (text, nullable)
trade_executions.con_id    (integer, nullable)
```

**`sec_type`** values from IBKR: `BAG` (combo summary), `FUT`, `FOP`, `OPT`,
`STK`, etc. This is the deterministic signal — `sec_type = 'BAG'` means combo
summary fill. No heuristic needed.

**`con_id`** stores the IBKR contract ID. The combo summary fill has the BAG
contract's conId; each leg fill has its own instrument conId. This enables
joining `trade_executions` back to the `contracts` table for richer leg-level
display (local_symbol, expiry, strike, right) without parsing the `raw` JSON.

**Ingestion:** both extracted from `fill.contract` during sync. Already
available in the fill object — just not persisted today.

### 2. Add `exec_role` to `trade_executions`

Explicit role tag computed during ingestion.

```sql
trade_executions.exec_role  (text, not null, default 'standalone')
```

Values:

| Value           | Meaning                                   |
| --------------- | ----------------------------------------- |
| `combo_summary` | Combo-level fill (secType=BAG, net price) |
| `leg`           | Individual leg of a combo fill            |
| `standalone`    | Regular non-combo execution               |

**Single-pass ingestion approach:**

1. During the per-fill loop, each execution is tagged based on its own
   `secType`: BAG → `combo_summary`, anything else → `standalone`.
2. After all fills are upserted, a single post-insert pass iterates over
   each touched trade's executions. If any execution is `combo_summary`,
   all sibling `standalone` executions are re-tagged to `leg`.
3. On subsequent syncs, the same logic runs — if a combo summary arrives
   late, existing standalones get re-tagged to `leg` automatically.

This avoids needing a two-pass scan of the full fill batch and handles
late-arriving combo summaries correctly.

### 3. Combo detection via `trades.sec_type`

No separate `is_combo` boolean is needed. The existing `trades.sec_type`
column already stores `'BAG'` for combo/spread trades (inherited from the
combo fill's contract during sync). This is the IBKR-native signal.

**Usage:**

- Query filter: `WHERE trades.sec_type = 'BAG'`
- UI: show Combo badge when `sec_type === "BAG"`
- Aggregation: if any canonical execution has `exec_role = 'combo_summary'`,
  use combo fills for quantity/price

### 4. Spread-aware aggregation using explicit fields

Replace the commission heuristic in `_recompute_trade_aggregates`:

**Before (heuristic):**

```python
has_commissioned = any(ex.commission and ex.commission > 0 for ex in canonical)
combo_fills = [ex for ex in canonical if not ex.commission or ex.commission == 0]
    if has_commissioned else []
```

**After (deterministic):**

```python
combo_fills = [ex for ex in canonical if ex.exec_role == "combo_summary"]
if combo_fills:
    # Spread — qty and avg_price from combo fills only
else:
    # Regular — qty and avg_price from all canonical fills
```

Benefits:

- No scanning for commission patterns.
- Indexed and queryable (`WHERE exec_role = 'combo_summary'`).
- Self-documenting: the column name explains the behavior.

## Migration

**Revision:** `e8a2c4d6f103` (depends on `d5f1a3b7c901`)

Schema changes:

1. `ALTER TABLE trade_executions ADD COLUMN sec_type TEXT`
2. `ALTER TABLE trade_executions ADD COLUMN con_id INTEGER`
3. `ALTER TABLE trade_executions ADD COLUMN exec_role TEXT NOT NULL DEFAULT 'standalone'`
4. `CREATE INDEX ix_trade_executions_sec_type ON trade_executions (sec_type) WHERE sec_type IS NOT NULL`
5. `CREATE INDEX ix_trade_executions_exec_role ON trade_executions (exec_role) WHERE exec_role != 'standalone'`

Data backfill (runs inline in the migration):

- `sec_type` ← `raw->'contract'->>'secType'`
- `con_id` ← `(raw->'contract'->>'conId')::int`
- `exec_role = 'combo_summary'` where `sec_type = 'BAG'`
- `exec_role = 'leg'` where sibling executions on the same trade have
  `sec_type = 'BAG'`
- `trades.sec_type = 'BAG'` for parent trades with combo fills

No destructive changes. Existing rows without `raw` contract data get
`sec_type=NULL`, `con_id=NULL`, `exec_role='standalone'`.

## Sync Service Changes

### Per-fill loop

```python
exec_sec_type = _safe_str(getattr(contract, "secType", None))
con_id = _safe_int(getattr(contract, "conId", None))
exec_role = "combo_summary" if exec_sec_type == "BAG" else "standalone"
```

### Post-insert pass (per touched trade)

```python
for trade_id in touched_trade_ids:
    trade_execs = session.query(TradeExecution).filter_by(trade_id=trade_id).all()
    has_combo = any(ex.exec_role == "combo_summary" for ex in trade_execs)
    if has_combo:
        trade.sec_type = "BAG"
        for ex in trade_execs:
            if ex.exec_role == "standalone":
                ex.exec_role = "leg"
```

### `_recompute_trade_aggregates`

```python
combo_fills = [ex for ex in canonical if ex.exec_role == "combo_summary"]
if combo_fills:
    total_qty = sum(abs(cf.quantity) for cf in combo_fills)
    weighted = sum(abs(cf.quantity) * cf.price for cf in combo_fills)
    avg_price = weighted / total_qty if total_qty > 0 else None
else:
    total_qty = sum(abs(ex.quantity) for ex in canonical)
    weighted = sum(abs(ex.quantity) * ex.price for ex in canonical)
    avg_price = weighted / total_qty if total_qty > 0 else None
```

## API Changes

### `GET /api/v1/trades/{trade_id}/executions`

- Add `sec_type`, `con_id`, and `exec_role` fields to `TradeExecutionResponse`.

## Frontend Changes

### Trades table

- Show a `Combo` badge on trades where `sec_type === "BAG"`.
- In the expanded executions view, show `exec_role` as a colored label:
  `combo` (violet) vs `leg` (amber). Standalone executions show `—`.

## Rollout

1. Alembic migration (additive, with inline backfill).
2. Update ORM models (`TradeExecution.sec_type`, `.con_id`, `.exec_role`).
3. Update sync service ingestion to populate new fields.
4. Update aggregation to use `exec_role` instead of commission heuristic.
5. Update API response schemas.
6. Update frontend (combo badge, exec_role labels).

## Acceptance Criteria

- Combo fills have `exec_role = 'combo_summary'`, `sec_type = 'BAG'`.
- Leg fills have `exec_role = 'leg'` with their actual `sec_type`.
- Non-combo executions have `exec_role = 'standalone'`.
- Parent trade `sec_type = 'BAG'` for combo trades.
- Parent trade `total_quantity` and `avg_price` use combo fills for combo
  trades and all fills for non-combo trades.
- Re-running sync is idempotent — fields are stable across repeated syncs.
- Commission heuristic is fully removed from aggregation code.
- Existing data is backfilled from `raw` JSON during migration.
