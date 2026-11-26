---
topics: ["trade-groups", "tags", "pnl", "frontend"]
code_dirs_or_files:
  [
    "src/services/trade_group_pnl.py",
    "src/services/tags.py",
    "frontend/src/components/strategies/GroupPnlSummary.tsx",
    "frontend/src/lib/strategies/groupPositions.ts",
  ]
description: (Status — not implemented) Spec for splitting a trade group's P&L card into a core position (the initial outlay, marked with a reserved `core` tag) and incremental trades that finance or hedge it, with support for rolling the core.
---

# Spec: Core vs Incremental P&L

> **Status: NOT IMPLEMENTED.** Build plan: [2026-11-26-0808-feat-core-incremental-pnl-plan.md](../plans/2026-11-26-0808-feat-core-incremental-pnl-plan.md).

## Problem

The group P&L card's "Capital invested" is `|Σ options cost basis| + |Σ other
cost basis|` over open positions (`groupCapital()` in
`frontend/src/lib/strategies/groupPositions.ts`). For a long-term position
financed by short options this misleads:

- The base is not anchored to the position being financed. A short call's
  credit nets against a long call (same bucket) but adds to stock (other
  bucket), so the same structure gets two rules.
- Closed financing trades vanish into Realized PnL. Nothing says how much of
  the outlay they paid back.
- The base moves on every roll, so the % moves when nothing important changed.

## Goal

For any group, answer: what did the core position cost, how much have the
other trades paid back, and where do I stand against the core cost. It must
work for any mix, not only long-vs-short:

- Long LEAP call, short calls against it.
- Long stock, covered calls.
- Long /ES put hedge rolled quarterly, short puts financing it.
- Long or short future, options against it.

Trade side (BUY/SELL) cannot tell core from incremental, so the user marks it.

## Rules

1. **Reserved tag `core`.** The user tags the orders that open the core
   position. All other trades in the group are **incremental** by default.
   The tag cannot be renamed, archived, or merged, and no other tag can be
   renamed or merged into it.
2. **Role is per contract, within the group.** A contract
   (`account_id`, `con_id`) is core if any of the group's orders on it carries
   `core`. Every fill on that contract counts as core, so the order that closes
   a core position (a roll's buy-back, an expiry) needs no tag.
3. **No lot splitting.** One contract has one role. To add exposure that is
   not core, trade a different contract (another strike or expiry).
4. **A combo is one order.** Tagging a combo `core` makes every leg core. A
   calendar opened as one order (long Dec'28 call, short Dec'26 call) puts the
   short leg in the core, so its premium lowers core cost instead of counting
   as financing. Later rolls of that short call are untagged, so the new
   contracts are incremental.
5. **Tags on orders only.** Tags on trades (and on live fills, which carry over
   to the settled trade) count. Tags on positions and groups do not: a position
   tag ends when the position goes flat, which would erase roll history.
6. **Scoped to the group.** The split only divides a group's existing figures.
   It never sums across groups and no other tag feeds a figure.
7. **Cost basis is IBKR's** (`avg_cost × position`, multiplier-inclusive). A
   core future's cost is its notional; no margin or allocated-capital input. An
   open **incremental** future adds nothing to incremental net: it costs no cash
   to open, so only its realized PnL counts and its open PnL stays in
   Unrealized.
8. **When the split shows.**
   - No `core` contract, or core cost = 0 → the card is unchanged.
   - Core cost > 0 (a debit core) → the full split.
   - Core cost < 0 (a short or credit core, e.g. a short future) → the split
     without **% financed** and **Net cost**, which assume an outlay.

## Figures

Over the group's apportioned positions and its fills, settled plus today's
unsettled ones:

| Figure                    | Definition                                                                                   |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| Core cost                 | Σ open cost basis of core contracts − Σ realized PnL of core fills                           |
| Incremental net           | Σ realized PnL of incremental fills − Σ open cost basis of incremental non-futures contracts |
| % financed                | incremental net ÷ core cost (debit core only)                                                |
| Net cost                  | core cost − incremental net (debit core only)                                                |
| Total PnL                 | unchanged (realized + unrealized)                                                            |
| Total / Unr. / Realized % | figure ÷ \|core cost\| (replaces ÷ capital)                                                  |

Core cost is the net cash spent on the core over the position's life, so a
roll keeps it one continuous position. Incremental net is the net cash the
other trades brought in: credits positive, debits (a bought hedge) negative.
The intraday block uses the same base.

## Examples

Illustrative figures.

**LEAP financed by short calls.** Long 1× 550C, avg cost 12,190.78 (`core`).
Closed short calls realized 327.15; one short call open at −79.95.

| Figure          | Value                      |
| --------------- | -------------------------- |
| Core cost       | 12,190.78                  |
| Incremental net | 327.15 + 79.95 = 407.10    |
| % financed      | 3.34%                      |
| Net cost        | 11,783.68                  |
| Total PnL       | −2,645.63, −21.70% of core |

**Calendar opened as one order (rule 4).** Buy Dec'28 550C for 12,190.78 and
sell Dec'26 550C for 800 in one combo tagged `core`. Later, an untagged roll
buys back Dec'26 for 300 and sells Jan'27 for 900.

| Figure          | Value                       |
| --------------- | --------------------------- |
| Core cost       | 12,190.78 − 500 = 11,690.78 |
| Incremental net | 900 (7.7% financed)         |

Opening the LEAP as its own order instead gives core cost 12,190.78 and
incremental net 1,400. Net cost and Total PnL are the same either way.

**Rolled /ES put hedge.**

| When | Order                                  | Role          | Core cost             |
| ---- | -------------------------------------- | ------------- | --------------------- |
| Q1   | Buy Mar 80% put, 3,000                 | core (tagged) | 3,000                 |
| Q1   | Sell puts, keep 1,200                  | incremental   | 3,000                 |
| Q2   | Sell Mar put for 500 (realized −2,500) | core (rule 2) | 0 + 2,500 = 2,500     |
| Q2   | Buy Jun put, 3,200                     | core (tagged) | 3,200 + 2,500 = 5,700 |

Core cost 5,700 = 3,000 + 3,200 − 500. % financed = 1,200 ÷ 5,700 = 21%.

**Short future core.** Short 1× /ES at 6,000 (`core`), short puts sold against
it for 3,000. Core cost −300,000; incremental net 3,000; Total PnL % is taken
against 300,000. % financed and Net cost are not shown.

## Card

Shown when the split applies (rule 8); replaces the Capital invested rows.

```
Core cost:          12,190.78
Incremental net:       407.10    3.34% financed
Net cost:           11,783.68
Total PnL:          −2,645.63   −21.70%
Unrealized PnL:     −2,972.78   −24.39%
Realized PnL:          327.15     2.68%
```

## Implementation notes

- Computed on the backend from the group's overlay and ledger
  (`src/services/trade_group_pnl.py`) and returned by the group detail
  endpoint as `core_cost` and `incremental_net` (both null when the split does
  not apply). Only the detail card reads them.
- Realized PnL is split by contract from leg fills. When the split does not
  reconcile to the group's realized PnL, the endpoint returns no split rather
  than wrong figures.

## Doc changes at ship

- `tags-and-tasks.md` rule 7: add the exception "the reserved `core` tag
  drives the core/incremental split of a group's P&L card; no other tag feeds
  a figure." Rule 4 is unaffected: role is derived, not tagged.
- Fold this spec into `strategies-and-trade-groups.md` (P&L card section) and
  delete it.

## Out of scope

- Lot-level splitting of one contract between roles.
- Per-leg roles inside one combo order.
- Margin or allocated-capital bases.
- Risk reversals and other cores that cost about zero.
- Tag-based figures outside a single group.
- The Strategy P&L list, the `trade_group_pnl` tool, and the per-account
  breakdown's Capital column.
