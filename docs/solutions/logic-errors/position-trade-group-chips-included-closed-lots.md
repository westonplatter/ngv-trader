---
title: Position trade-group chips included closed lots because attribution was per-instrument
date: 2026-08-17
category: logic-errors
module: positions_api
problem_type: logic_error
component: api_router
symptoms:
  - "A single held position renders multiple Trade Group chips, one per campaign the instrument ever traded under"
  - "Chips for closed, round-tripped campaigns appear alongside the chip for the lot actually held"
  - "Re-entering the same con_id under a different campaign weeks later permanently adds a stale chip"
  - "Nothing errors — the API returns 200 and the UI renders exactly what the query produced"
root_cause: scope_issue
resolution_type: code_fix
severity: medium
tags:
  - trade-groups
  - positions
  - fifo
  - open-lots
  - execution-attribution
  - outer-join
  - derived-attribution
related_components:
  - database
---

# Position trade-group chips included closed lots because attribution was per-instrument

## Problem

`GET /positions` attributed trade groups to a position by joining _every_ `TradeExecution` on the instrument to its group, with no notion of whether that fill was still open. A liquid future re-entered under a new campaign therefore carried a chip for every campaign it had ever passed through, including ones closed out weeks earlier.

## Symptoms

- A single Positions row (MNQU6, `con_id` `1000000001`, position `+1`) rendered **three** "Trade Group" chips where the operator expected one — the group of the trade that opened the quantity actually held.
- The extra chips named campaigns that were already flat; only one was live.
- The effect scales with instrument reuse: the more times a con_id round-trips under different campaigns, the more dead chips accumulate on the live row.
- Nothing errored. The API returned 200 and the UI rendered exactly what the query produced.

## What Didn't Work

**The naive reading — "the operator mis-tagged the fills" — was wrong.** Tagging in this codebase is per-**fill**, not per-instrument: `trade_group_executions` carries a unique constraint on `trade_execution_id` (`src/models.py:517`), so one settled execution belongs to at most one group. There is no `TradeGroupMember` table and groups do not own instruments. Every fill on the affected instrument was tagged to the campaign it was actually traded under. Reading the fills read-only against prod confirmed it — 11 settled fills forming five clean round-trips plus one open leg:

```text
fills 1-2    2025-01-06 -> 2025-01-13   BUY/SELL  O/C   Nasdaq Covered Calls
fills 3-4    2025-01-14 -> 2025-01-15   BUY/SELL  O/C   Nasdaq Covered Calls
fills 5-6    2025-01-21                 BUY/SELL  O/C   Equity Hedge - Dec25
fills 7-8    2025-01-23                 BUY/SELL  O/C   Equity Hedge - Dec25
fills 9-10   2025-01-27                 BUY/SELL  O/C   Long Risk Assets
fill  11     2025-01-29                 BUY       O     Long Risk Assets
```

Ten fills net to flat. Only fill 11 constitutes the held `+1`. **Re-entering the same con_id under a different campaign weeks later is normal desk behavior for a liquid future**, not a data-entry mistake. The tagging was correct; the read path was wrong. Chasing the data would have "fixed" it by destroying accurate history.

**The inner-join trap — the obvious implementation silently corrupts the lot walk.** The natural way to write an open-lot walk is to reuse the existing query, which inner-joined `TradeExecution -> TradeGroupExecution -> TradeGroup`. That query only yields _tagged_ fills. But an untagged fill still **consumes open quantity** — it closes a lot just as effectively as a tagged one. Walking only tagged fills makes closing quantity disappear from the walk, so lots that were actually closed survive it and get attributed to the live row. The failure is silent: no error, no missing rows, just a wrong answer that looks plausible. The join had to become an **outer** join (`src/api/routers/positions.py:216`, `:220`) precisely so untagged fills participate in the matching while contributing no chip.

**Unsigned FIFO is a known dead end here (session history).** An earlier cost-basis investigation hand-rolled a FIFO matcher over `trade_executions` and its first pass — consume oldest lots first, unsigned — produced wrong answers and had to be rewritten with signed lot handling before it reconciled. Short and option legs mean a fill can open in either direction, so quantity sign must drive whether a fill opens or consumes a lot; `buy = open` is not a safe assumption. The matcher here is signed from the start for that reason.

**Two smaller things worth not re-deriving:**

- Deriving a sign from `side` is unnecessary **on the FlexQuery path** — but the guarantee is an assumption, not an invariant the tree enforces. `TradeExecution.quantity` is a plain `Float` (`src/models.py:434`) copied verbatim from FlexQuery's `quantity` field with no sign derivation anywhere (`src/services/trade_sync_flexquery.py:388`, `:487`); the walk depends on IBKR delivering it already signed. The nearest in-tree corroboration is that the same module infers combo side from `signed_cash += qty * px` (`:629`, `:677`), which is only meaningful if `qty` carries sign. **The dormant TWS path stores it unsigned** — `src/services/trade_sync_tws.py:282` writes `shares`, which `ib_async` always reports positive, keeping the sign in `side` instead. `_open_lot_trade_groups` does not filter on `data_source` (`src/api/routers/positions.py:214-221`), so reviving the TWS trade sync would feed unsigned rows into the matcher and silently corrupt every lot walk. Fix the sign at ingest if that path is ever brought back.
- Exact float comparison against zero does not hold here. Fractional share quantities (DRIP / dividend reinvestment) are real in this data, so the matcher guards with `_QTY_EPSILON = 1e-9` (`src/api/routers/positions.py:44`).

Ruff `C901`/`PLR0912` fired on the first single-function version of the walk (complexity 12 > 10, branches 10 > 8). Extracting the per-fill matcher into `_apply_fill_fifo` resolved it and made the matcher independently readable.

## Solution

Attribute chips to the **open lots**, computed by a FIFO walk over all fills. Applied to `src/api/routers/positions.py`.

Before — one flat rollup of every tagged fill, inner-joined:

```python
settled_rows = db.execute(
    select(TradeExecution.account_id, TradeExecution.con_id, TradeGroup.id, TradeGroup.name)
    .join(TradeGroupExecution, TradeGroupExecution.trade_execution_id == TradeExecution.id)
    .join(TradeGroup, TradeGroup.id == TradeGroupExecution.trade_group_id)
    .where(TradeExecution.con_id.is_not(None))
    .distinct()
    .order_by(TradeGroup.id.asc())
).all()
for account_id, con_id, group_id, group_name in [*settled_rows, *live_rows]:
    trade_group_acc.setdefault((account_id, con_id), {}).setdefault(
        group_id, TradeGroupRef(id=group_id, name=group_name)
    )
```

After — a FIFO lot matcher (`src/api/routers/positions.py:166`):

```python
def _apply_fill_fifo(lots: list[list], quantity: float, group: TradeGroupRef | None) -> None:
    """Match one signed fill against ``lots`` FIFO, mutating it in place."""
    remaining = quantity
    while abs(remaining) >= _QTY_EPSILON and lots and (lots[0][0] > 0) != (remaining > 0):
        matched = min(abs(remaining), abs(lots[0][0]))
        lots[0][0] -= matched if lots[0][0] > 0 else -matched
        remaining -= matched if remaining > 0 else -matched
        if abs(lots[0][0]) < _QTY_EPSILON:
            lots.pop(0)
    if abs(remaining) >= _QTY_EPSILON:
        lots.append([remaining, group])
```

driven by `_open_lot_trade_groups` (`:183`), which walks **all** fills in execution order:

```python
    .select_from(TradeExecution)
    .outerjoin(TradeGroupExecution, TradeGroupExecution.trade_execution_id == TradeExecution.id)
    .outerjoin(TradeGroup, TradeGroup.id == TradeGroupExecution.trade_group_id)
    .where(TradeExecution.con_id.is_not(None))
    .order_by(
        TradeExecution.account_id.asc(),
        TradeExecution.con_id.asc(),
        TradeExecution.executed_at.asc(),
        TradeExecution.id.asc(),
    )
```

Shape of the change:

- Returns a **tuple** `(open_lot_map, all_fills_map)` — the open-lot attribution plus the old unfiltered rollup, kept as a fallback.
- Ordering is `(account_id, con_id, executed_at, id)`; the trailing `id` makes same-timestamp fills deterministic (`:222-227`).
- Unsettled TWS fills (`trade_group_live_executions`) are **open by definition** and are always unioned into the open map (`:249-265`). Their uniqueness is on `ib_exec_id` (`src/models.py:587`), and the settled link is carried over on settlement, so a fill is never counted twice.
- `_groups_for` (`:273`) returns open-lot groups, falling back to the historical rollup when the open-lot walk yields nothing for a position that _is_ held. Both call sites — the settled position rows (`:371`) and the live-only rows (`:432`) — go through it.

```python
def _groups_for(key, open_map, all_map) -> list[TradeGroupRef]:
    groups = open_map.get(key)
    if groups:
        return groups
    return all_map.get(key, [])
```

The user-facing rule this produces is documented in [trade-tagging.md](../../trade-tagging.md) under _Which groups a position row shows_; this learning records the failure, the evidence, and the reusable technique rather than restating the rule.

## Why This Works

**Root cause: a set-membership question was asked where a quantity question was needed.** "Which groups has this instrument ever touched?" is a `SELECT DISTINCT` over a join. "Which groups make up the quantity I hold right now?" is a lot-matching problem, and no join expresses it — the answer depends on the _order_ fills arrived and how much quantity each consumed. The old code answered the first question and labeled it as the second. Every chip it emitted was factually true and none of them were the answer.

**FIFO is the right frame because a position is a queue of lots, not a bag of tags.** Brokers, tax lot accounting, and the desk's own mental model all treat a close as consuming the oldest open lot. Attribution has to inherit that: a chip on a live row means "some of what I hold was opened by a fill in this group," which is only decidable by replaying opens and closes in order. The FIFO walk is a direct encoding of that definition, which is why it needs no per-instrument special-casing — futures, options, and fractional-share stock all fall out of the same loop. It also handles a fill that closes an existing lot and opens an opposite one in the same execution (IBKR tags these `C;O`): the `while` consumes the opposing lots and the remainder appends a new one, with no special case.

**Untagged fills must participate or the walk is meaningless.** Open quantity is a property of the instrument, not of any group. Filtering the walk by tag changes the arithmetic, not just the labels. The outer join is the load-bearing detail of the whole fix.

**The fallback is a correctness hedge, not laziness.** An empty open-lot set for a position that is genuinely held means the fill history does not reconcile — transferred-in lots, fills predating the sync window. The FIFO walk cannot distinguish "nothing is open" from "I never saw the opening fill." Showing the historical rollup there is strictly better than showing an empty cell, and it is exactly what kept the four non-reconciling positions from losing their chips.

**Scope boundary — this walk is for attribution, never for money.** [The tax-adjusted cost-basis plan](../../plans/2026-08-08-001-feat-tax-adjusted-cost-basis-reporting-plan.md) (KTD2) explicitly _rejected_ reconstructing FIFO lots from execution history, because doing so means guessing IBKR's lot-matching algorithm — a prior attempt reproduced an observed adjustment only to within about one percent. That rejection still stands and is not contradicted here. This walk answers "whose chip goes on this row," a question where a small divergence from IBKR's matcher is invisible. Dollar cost basis and tax lots must keep coming from IBKR (`originatingOrderID` join, `fifoPnlRealized`). Do not cite this code as precedent for deriving basis.

**Interaction worth knowing:** a synthetic `trade_executions` row (`ib_exec_id` prefixed `SYNTH-`) exists in prod to back an open futures position that had no real opening fill. It participates in the FIFO walk exactly like a real fill — that is what makes that position attributable at all. Deleting a synthetic opener without a real fill to replace it will silently drop the position into the `_groups_for` fallback.

## Prevention

**Verify an attribution change by diffing old vs new across the whole live dataset before shipping.** This is [the house verification pattern](./bag-combo-summary-purge-deadlocks-on-peer-summaries.md) — a read-only old-vs-new comparison over real rows, including a control that must not change — applied to a read path rather than a purge predicate:

1. Run both the old and new attribution functions in one read-only process against the real DB.
2. Diff the output per key across **every** row, not a sample.
3. Expect and justify the delta count.

Result here: **exactly one row changed** out of 77 positions — three chips to one. The other 76 were byte-identical, and those 76 are the control. That is the evidence the change is surgical rather than a broad behavior shift, and it is not obtainable from a unit test on synthetic data.

**Pair it with an independent reconciliation check.** Sum signed fill quantities per `(account_id, con_id)` and compare to the stored position quantity — that tells you where the FIFO walk is operating on incomplete history _before_ users find it. Result here: 72 reconciled, 4 mismatched (fractional DRIP share positions, plus one option whose fills net to 2 with 1 held), 1 with no fill history at all. None lost chips, because the fallback caught them. Run the reconciliation _first_; it sizes the fallback's blast radius.

**IBKR already stamps open/close on most fills — use it as a cross-check, not a replacement.** `trade_executions.raw["openCloseIndicator"]` carries IBKR's own determination. Measured over prod: 2360 `O`, 2300 `C`, 10 `C;O`, 728 null, 5 empty — about 86% clean coverage. Enough to assert against the FIFO walk's opinion on the fills that have it, not enough to drive attribution on its own. Note `raw` is `json`, not `jsonb`, so containment operators do not apply; `->>` works.

```bash
task test                                        # 144 passed
trunk check
uv run python scripts/check.py src.api.routers.positions
uv run python scripts/doc_check.py
uv run python scripts/ibkr_sensitive_data_check.py
```

**Test-coverage gap — flagged, not closed.** There is **no automated test** over the new FIFO attribution. Verification was a one-off read-only prod diff, which does not survive into CI. The suite began as a dependency-bump canary and has since grown real behavior tests in a few areas (flexquery tokens, two-phase sync, crypto), but nothing touches positions attribution — the only `positions` references in `tests/` assert the route is registered and the table exists. No existing test would catch a regression here. `_apply_fill_fifo` is a pure function over `(lots, quantity, group)` and is trivially unit-testable; the cases that matter are: full close, partial close, over-close flipping sign (`C;O`), untagged fill closing a tagged lot, fractional quantities near `_QTY_EPSILON`, and same-timestamp ordering.

**Read and write paths must be reasoned about as a pair.** The read path is now open-lot scoped; the **write path is not**. `POST /trade-groups/{id}/positions:assign` (`src/api/routers/trade_groups.py:640`) and `:unassign` (`:731`) both still fan out to every fill matching `(account_id, con_id)` with no open/closed filter. Consequences, pre-existing and unchanged by this fix:

- Clicking the `x` on a chip strips that group from **closed historical round-trips** too, not just the open lot.
- Assigning a position to a group retroactively re-tags **closed lots** into it.

The same endpoint carries [a separate silent-204 defect](./tws-fills-window-anchored-to-session-roll.md) when a position has no executions at all. Together those two are the full description of the write-path gap. Anyone tightening it should reuse the open-lot walk rather than reimplementing the matching.

**When a UI shows "too many" of something derived from history, suspect the rollup before the data.** The instinct to blame tagging cost time and would have caused damage. The diagnostic question is: _does this query know about time or state at all?_ A `SELECT DISTINCT ... JOIN` over an append-only history table cannot, by construction, answer a question about the present.

## Related

- [Trade tagging](../../trade-tagging.md) — per-fill membership model and the current open-lot chip rule.
- [Intraday TWS overlay](../../core/intraday-tws-overlay.md) — the `/positions` merge the chip map hangs off, and the live/settled two-tier model that makes unsettled fills unconditionally open.
- [Intraday fills window anchored to the session roll](./tws-fills-window-anchored-to-session-roll.md) — the opposite failure on the same UI element (zero chips, not too many), and the write-path silent-204 sibling.
- [Peer BAG combo summaries deadlocked the purge](./bag-combo-summary-purge-deadlocks-on-peer-summaries.md) — origin of the read-only old-vs-new verification rule reused here.
- [Auto-tag suggestions spec](../../spec-auto-tag-suggestions.md) — its core matching question ("which group holds the open position this fill is closing") now has a working primitive in `_open_lot_trade_groups`; reuse it rather than writing a second matcher.
- [Tax-adjusted cost-basis plan](../../plans/2026-08-08-001-feat-tax-adjusted-cost-basis-reporting-plan.md) — KTD2 rejects FIFO reconstruction for _basis_; U3/U4 would add a `position_lots` table. That table does not exist yet, so executions remain the only lot source. If it lands, reconcile this walk against it instead of keeping two notions of a lot.
