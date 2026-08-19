---
topics: ["semantic-layer", "metrics", "analytics", "agent-tools", "osi"]
code_dirs_or_files:
  [
    "osi/ngv_semantic_model.yaml",
    "src/services/semantic/",
    "src/mcp/semantic_server.py",
    "src/services/trade_group_pnl.py",
  ]
description: Analyst-facing catalog for the semantic layer — metrics, dimensions, grains, and worked examples for query_metric and trade_group_pnl tools.
---

# Semantic Data Model — what the MCP can answer

> **Audience: an analyst driving the semantic layer through MCP** (`describe_semantic_model`,
> `query_metric`, `trade_group_pnl`). This is the _catalog_ — the data elements you
> can name and what they mean. For the design, invariants, and how to extend it,
> read [semantic-queries.md](semantic-queries.md).
>
> **You never write SQL.** You pick a **metric**, optional **dimensions** to group
> by, optional equality **filters**, and an optional **date range** on the time
> axis. The resolver compiles the SQL. `describe_semantic_model` is always the
> live source of truth; this doc explains what those names are _for_.

## 1. Start here — the four tools

| Tool                                                                               | Use it for                                                                                                                                                        |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `describe_semantic_model()`                                                        | List every metric + dimension + which grain each lives on. Call first.                                                                                            |
| `query_metric(metric, group_by, filters, start_date, end_date, time_grain, limit)` | Run one metric, sliced by dimensions. Returns rows **+ the compiled SQL**.                                                                                        |
| `find_trade_groups(query, limit)`                                                  | **Fuzzy-find a trade group by a free-text phrase** ("MP", "gamma delta", "covered call") when you don't know the exact name. Resolution step before PnL (see §8). |
| `trade_group_pnl(group)`                                                           | Realized + settled + **intraday/live** unrealized PnL for one trade group. Accepts an id, exact name, or an unambiguous fuzzy phrase (see §5, §8).                |

## 2. The grains (facts) — pick a metric, you pick a grain

Every metric lives on exactly **one grain**. A dimension is usable with a metric
only if it's reachable from that metric's grain (`describe` lists the valid ones
per metric; an invalid pick errors with the valid options).

| Grain (fact)      | Physical view       | One row per                         | Metrics here                                                                                            |
| ----------------- | ------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `execution_facts` | `v_execution_facts` | canonical fill                      | `realized_pnl`, `total_commissions`, `fill_count`, `gross_premium`, `premium_collected`, `premium_paid` |
| `trade_facts`     | `v_trade_facts`     | trade                               | `trade_count`, `win_rate`                                                                               |
| `position_facts`  | `v_position_facts`  | **open** position (`position <> 0`) | `open_position_count`, `net_quantity`, `position_market_value`, `settled_unrealized_pnl`                |

## 3. Metrics catalog

**Money & activity (execution grain)**

- `realized_pnl` — net booked PnL (FlexQuery `fifoPnlRealized`). Only populated when a position is (partly) closed.
- `total_commissions` — fees paid. Excludes synthetic `combo_summary` rows.
- `fill_count` — number of real fills. Excludes synthetic `combo_summary` rows.

**Cash flow / premium (execution grain)** — from IBKR's signed `proceeds` (SELL = cash in, BUY = cash out):

- `premium_collected` — cash received on SELL fills (credits), positive USD. _Covered-call premium sold._
- `premium_paid` — cash paid on BUY fills (debits), positive USD. _Cost to open a long option / buy-to-close._
- `gross_premium` — net cash flow = collected − paid (signed). Positive = net credit.

**Trade grain**

- `trade_count`, `win_rate` (fraction of realized trades that are winners).

**Open positions (position grain)**

- `open_position_count`, `net_quantity` (signed), `position_market_value`, `settled_unrealized_pnl` (end-of-day snapshot; see §5).

## 4. Dimensions — how to slice

| Dimension                    | On grain(s)                                    | Notes                                                                                                                                                           |
| ---------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `account`                    | all                                            | Human alias (`main`, `sep`, `lsc`, `mini`) — never the raw account number.                                                                                      |
| `tag`                        | execution, position                            | **Trade group / strategy name.** The key slice for a strategy review.                                                                                           |
| `sec_type`                   | execution, position, trade                     | STK / FUT / OPT / FOP. On execution & position grains it comes straight off the fill/position, so it's **always populated** — use it to split stock vs options. |
| `symbol`                     | all                                            | Underlying ticker. Native (complete) on `trade_facts`/`position_facts`; on `execution_facts` it comes via the `contracts` join — see the caveat below.          |
| `expiration`                 | **position** (time axis)                       | Contract last-trade date. **Range-filter** it (`start_date`/`end_date`) for "expiring in the next N days". NULL for stock.                                      |
| `days_to_expiration`         | position                                       | Whole days until expiration. For **display/grouping**; to filter a horizon, range-filter `expiration` instead.                                                  |
| `executed_at`                | execution / trade (time axis)                  | Fill/trade time. Range-filter for date windows.                                                                                                                 |
| `right`, `strike`            | position (native); execution (via `contracts`) | ⚠️ Complete on `position_facts` — see the caveat below for `execution_facts`.                                                                                   |
| `contract_month`             | execution (via `contracts`)                    | ⚠️ See the caveat below.                                                                                                                                        |
| `exchange`, `side`, `status` | see `describe`                                 | —                                                                                                                                                               |

⚠️ **On `execution_facts`, `strike` / `right` / `contract_month` / `symbol` all
come from a join to the `contracts` security master, which is incomplete for
many traded option `con_id`s.** Slicing an execution-grain metric by these can
silently **drop** fills whose contract isn't in the master. On `position_facts`,
`strike`/`right`/`symbol` are native columns and always complete — only
`contract_month` isn't available on that grain. Totals by `tag` / `sec_type`
(which don't touch `contracts`) are complete; execution-grain strike-level
breakdowns are best-effort until contract coverage is backfilled.

## 5. Unrealized PnL — settled (SQL) vs intraday (tool)

Two different figures; don't confuse them:

- **Settled unrealized** = `settled_unrealized_pnl` (a real metric). End-of-day
  snapshot. Filter by `tag` to get one group's number.
- **Intraday / live unrealized** = **`trade_group_pnl(group)` only.** It's a
  read-time merge of live TWS marks over the settled snapshot — not expressible in
  SQL — and returns `settled_unrealized_pnl`, `intraday_unrealized_pnl`,
  `intraday_total_pnl`, realized, and `marks_as_of`.

**Attribution caveat (both):** unrealized-by-group is a _per-group_ attribution —
a position shared by two groups counts in **both**. So `settled_unrealized_pnl`
summed with **no `tag` filter double-counts** shared positions. **Query one group
at a time.**

## 6. Worked example — covered-call financing for a trade group

_"For MP LT: how much option premium have we collected vs. paid for the long
LEAP, and where do realized/unrealized stand?"_ — all via MCP:

| Question                              | Call                                                                                    |
| ------------------------------------- | --------------------------------------------------------------------------------------- |
| Premium collected (options only)      | `query_metric("premium_collected", filters={tag:"MP LT", sec_type:"OPT"})` → **$1,451** |
| Premium paid on options (incl. LEAP)  | `query_metric("premium_paid", filters={tag:"MP LT", sec_type:"OPT"})` → **$2,299**      |
| Net cash flow, all legs (incl. stock) | `query_metric("gross_premium", filters={tag:"MP LT"})` → **−$6,863**                    |
| Realized PnL                          | `query_metric("realized_pnl", filters={tag:"MP LT"})` → **$1,100**                      |
| Settled unrealized PnL                | `query_metric("settled_unrealized_pnl", filters={tag:"MP LT"})` → **−$1,383**           |
| Live/intraday unrealized              | `trade_group_pnl("MP LT")` → intraday unrealized **−$1,246**                            |

Financing so far ≈ collected $1,451 / LEAP cost $2,176 ≈ **67%**. (Isolating the
_exact_ LEAP leg by `strike`/`right` is limited by the contracts caveat in §4.)

## 7. Other common questions

- **Open positions by account & type:** `open_position_count` grouped by `["account","sec_type"]`.
- **What's expiring in 30 days:** `open_position_count` grouped by `["sec_type","days_to_expiration"]`, `start_date`=today, `end_date`=today+30.
- **Unrealized exposure by account & type:** `settled_unrealized_pnl` grouped by `["account","sec_type"]`.
- **Realized PnL by strategy this quarter:** `realized_pnl` grouped by `["tag"]`, date range on `executed_at`.

## 8. Finding a trade group by phrase (`phrase → find → PnL`)

You often don't know a group's exact name — you have a phrase ("MP", "gamma
delta", "the CL Dec 27 thing"). **Don't filter a metric by `symbol` to find it**:
on `execution_facts`, `symbol` comes from the incomplete `contracts` join (§4),
so symbol-filtered PnL silently undercounts, and a symbol isn't even the right
key (the phrase may be a strategy description, not a ticker). Use the two-step
flow:

1. **Resolve** — `find_trade_groups("gamma delta")` → `[{id:19, name:"CL Short Gamma + Long Delta --- Dec'27", score:…}]`.
   Every token in the phrase must appear in the name (order/punctuation-independent),
   so `"gamma delta"`, `"cl dec 27"`, `"dec'27"` all hit the same group. If **more
   than one** match comes back the phrase is ambiguous (e.g. `"dec 27"` → GOOGL,
   CL, HE Butterfly) — pick one, don't guess.
2. **Look up** — pass the chosen `id` (or exact `name`) to:
   - `trade_group_pnl(19)` → realized + settled + intraday unrealized in one call, or
   - `query_metric(..., filters={tag: name})` for a specific metric.

`trade_group_pnl` also accepts a fuzzy phrase directly and auto-resolves it **when
unambiguous**; an ambiguous phrase raises an error listing the candidate groups
(it never silently picks one).

> **Names only.** Matching is against the trade-group **name**. A strategy whose
> name doesn't contain the symbol/phrase you typed won't be found — rename the
> group or search a term that's actually in the name.
