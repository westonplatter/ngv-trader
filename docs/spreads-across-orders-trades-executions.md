# Spreads Across Orders, Trades, and Executions

## Purpose

Document how ngtrader handles spread/combo trades as a first-class concept
across the orders, trades, and trade executions layers. Spreads are not an
edge case — they are a primary trading pattern and the system must represent
them correctly at every level.

## IBKR Spread Execution Model

When a combo/spread order is filled, IBKR produces three types of data:

### 1. The combo-level fill (the spread itself)

- `contract.secType = "BAG"`
- `execution.execId` ends in `.01.XX` (lowest sub-ID within the fill group)
- `commission = 0` (no commission on the synthetic combo fill)
- `price` = net debit or credit of the spread
- `quantity` = number of spreads traded
- `side` = overall direction (`BOT` = bought the spread, `SLD` = sold it)

This is the **source of truth** for the spread's price and quantity.

### 2. Individual leg fills

- `contract.secType` = the actual instrument type (`FUT`, `FOP`, `OPT`, etc.)
- `execution.execId` ends in `.02.XX`, `.03.XX`, etc.
- `commission > 0` (real commissions per leg)
- `price` = the leg's individual fill price
- `quantity` = contracts per leg (may differ in ratio spreads)
- `side` = leg direction (`BOT` or `SLD`)

These are the **real market fills**. The combo fill's net price equals the
algebraic combination of these leg prices.

### 3. The order wrapper

- `order.contract.secType = "BAG"`
- `order.contract.comboLegs` contains the leg definitions (conId, ratio, action)
- `order.orderRef` may be a generic tool name like `"SpreadTrader"` (shared
  across many orders, not unique)

### Exec ID structure for spreads

All fills from one combo execution share the same base prefix, with the
sub-component after the second-to-last dot distinguishing combo vs legs:

```
000100c2.699f7eb6.01.01   combo summary (secType=BAG)
000100c2.699f7eb6.02.01   leg 1
000100c2.699f7eb6.03.01   leg 2
```

The final `.01` is the correction revision (see spec-trades-and-executions-sync.md).

## Spread Structures

Spreads are not always two-legged. Common structures include:

| Structure   | Example          | Legs                    |
| ----------- | ---------------- | ----------------------- |
| Vertical    | Bull call spread | long + short            |
| Calendar    | CL time spread   | short front + long back |
| Butterfly   | Long butterfly   | short + long×2 + short  |
| Ratio       | 1×2 ratio spread | long + short×2          |
| Iron condor | IC               | 4 legs                  |

In all cases, IBKR produces one combo fill (the spread) plus N leg fills.
The combo fill's quantity and price are always the spread-level values.

## How Each Layer Handles Spreads

### Orders layer (`orders` + future `order_legs`)

The order represents the intent to trade. For a combo order:

- `orders.sec_type = "BAG"`
- `orders.symbol` = underlying (e.g. `CL`)
- `orders.quantity` = number of spreads
- Leg details come from `order.contract.comboLegs` (persisted in `order_legs`
  when spec-bag-order-combo-visibility is implemented)

See `docs/spec-bag-order-combo-visibility.md` for the full order-legs design.

### Trades layer (`trades`)

The trade is the parent aggregate over executions. For a combo trade:

- `trades.sec_type = "BAG"` (set from the combo fill's contract during sync)
- `trades.total_quantity` = spread quantity (from combo fills only)
- `trades.avg_price` = net spread price (from combo fills only)
- `trades.side` = spread direction

Combo detection: `trades.sec_type = 'BAG'`. No separate `is_combo` flag
needed — the IBKR secType is the native signal.

### Executions layer (`trade_executions`)

All fills are stored — both the combo summary and each leg. Every execution
is canonical (unless it has been superseded by an IBKR correction).

Each execution row carries three spread-related columns:

| Column      | Purpose                                           |
| ----------- | ------------------------------------------------- |
| `sec_type`  | IBKR contract secType (`BAG`, `FUT`, `FOP`, etc.) |
| `con_id`    | IBKR contract ID (for joins to `contracts` table) |
| `exec_role` | `combo_summary`, `leg`, or `standalone`           |

**Aggregation rule for parent trade:**

1. **If any canonical execution has `exec_role = 'combo_summary'`:** this is
   a combo/spread trade. Use only the combo_summary fills for
   `total_quantity` and `avg_price`. Leg fills are retained for audit and
   detail views.

2. **Otherwise:** this is a regular (non-spread) trade. Sum all canonical
   execution quantities and compute a weighted average price.

**`exec_role` assignment during sync (single pass):**

1. Per-fill loop: `secType == "BAG"` → `combo_summary`, else `standalone`.
2. Post-insert pass per trade: if any execution is `combo_summary`, re-tag
   all sibling `standalone` executions to `leg`.
3. On re-sync: same logic runs — late-arriving combo summaries correctly
   re-tag existing standalones.

## Design Principles

1. **Spreads are first-class.** Every layer (orders, trades, executions) must
   correctly represent spread quantity, price, and structure. A 10-lot spread
   shows quantity 10, not 30 (sum of legs + combo).

2. **The combo fill is the spread's source of truth.** Its price is the net
   debit/credit. Its quantity is the number of spreads. Its side is the
   overall direction.

3. **Leg fills are components, not independent trades.** They belong to the
   same parent trade and provide per-leg detail (individual prices,
   commissions, exchanges). They do not drive parent trade aggregates.

4. **`order_ref` is not a unique identifier.** IBKR tools like SpreadTrader
   reuse the same `order_ref` across many unrelated orders. Only
   `ngtrader-*` prefixed refs are treated as unique keys for trade matching.

5. **Store everything, aggregate carefully.** All fills (combo + legs) are
   persisted in `trade_executions` with full `raw` JSON for audit. The
   aggregation logic on the parent trade selects which fills drive the
   summary.

6. **Use IBKR's native signals, not heuristics.** `secType = "BAG"` and
   `exec_role = "combo_summary"` are deterministic. The old commission=0
   heuristic has been replaced.

## Current Implementation

### Schema

- `trade_executions.sec_type` — IBKR contract secType, extracted from fill
- `trade_executions.con_id` — IBKR contract ID, enables joins to `contracts`
- `trade_executions.exec_role` — `combo_summary`, `leg`, or `standalone`
- `trades.sec_type` — `"BAG"` for combo trades (no separate `is_combo` flag)

### What works

- Combo fills and leg fills are ingested with correct `sec_type`, `con_id`,
  and `exec_role` tags.
- Parent trade aggregates use `exec_role = 'combo_summary'` fills for
  quantity and price on combo trades.
- `trades.sec_type = "BAG"` propagates from the combo fill's contract.
- All fills are visible in the executions detail view with role badges
  (combo = violet, leg = amber).
- Correction handling (revision tracking, canonical flags) works for both
  combo and leg fills.
- Existing data is backfilled from `raw` JSON during migration.

### Spread inference for individually-legged trades

See `docs/spec-trades-and-executions-sync.md` (Spread Inference section).
For positions legged in individually (no BAG order), spread membership is
inferred from shared `ib_order_id` or `ngtrader-spread-*` order refs, then
confirmed by the operator.

## Related Docs

- `spec-trades-and-executions-sync.md` — trade/execution sync and spread
  inference design
- `spec-first-class-spread-fields.md` — sec_type, con_id, exec_role schema
  and deterministic aggregation spec
- `spec-bag-order-combo-visibility.md` — BAG order leg persistence and UI
- `spec-client-portal-combo-spreads.md` — CPAPI combo position sync
  (native IBKR spread linkage for positions)
