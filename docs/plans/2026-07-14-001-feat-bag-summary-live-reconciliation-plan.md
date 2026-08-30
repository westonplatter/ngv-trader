---
title: "feat: Reconcile orphaned live BAG combo-summary executions"
type: feat
status: shipped
created: 2026-07-14
---

# feat: Reconcile orphaned live BAG combo-summary executions

**Shipped 2026-08-01** via Option 1 (leg-anchored purge) on Fix C's order key,
with one deviation the plan did not anticipate: the settled synthesized combo
summary carries NULL `ib_perm_id`/`ib_order_id`/`con_id`, so "the legs settled"
cannot be proven through the settled side's order key. The matcher proves it
from the live side instead (no sibling shares the order key) and corroborates
with settled `leg` rows at the summary's account and `exec_time`. The group tag
fans out onto every settled leg via `carry_over_link_to_executions`, since there
is no single settled row to hand it to. Current behavior is documented in
[../core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md#orphan-reconciliation).

## Summary

`reconcile_orphaned_live_executions` (`src/services/live_reconcile.py`) now
clears two of the three classes of phantom "unsettled" `live_executions` rows —
combo-leg id normalization (leg-strip) and expiration/assignment/exercise book
events. It intentionally leaves a **third** class untouched: **live BAG
combo-summary rows**, which have no settled counterpart keyed by `con_id` and
cannot be matched by the shipped matchers.

At authoring time there are **4** such orphans (all realized P&L `0`, so no
dollar impact — but they persist forever and clutter the Trades table, and one
of them was preemptively tagged to a group):

| id  | symbol | ib_exec_id                | side | qty | price | when             | tagged group |
| --- | ------ | ------------------------- | ---- | --- | ----- | ---------------- | ------------ |
| 64  | VIX    | `0000abcd.12345678.01.01` | SLD  | 1   | 0.45  | 2025-01-15 10:30 | —            |
| 67  | VIX    | `0000efgh.5678ijkl.01.01` | SLD  | 1   | 0.45  | 2025-01-15 10:30 | —            |
| 54  | SPCX   | `0000efgh.23456789.01.01` | BOT  | 1   | 9.65  | 2025-01-15 11:45 | 46           |
| 144 | MARA   | `0000ijkl.34567890.01.01` | BOT  | 1   | −0.46 | 2025-01-16 15:30 | 35           |

All carry the placeholder BAG `con_id = 400000001` and `sec_type = "BAG"`.

This plan scopes reconciling that class. It has a hard dependency on capturing an
**order grouping key** on `LiveExecution` — the same key the contract-parity plan
already scopes as **Fix C / U3**
(`docs/plans/2026-07-08-001-feat-unsettled-tws-contract-parity-plan.md`).

---

## Problem Frame

### Why BAG summaries orphan

The intraday feed (`ib.fills()`) delivers a combo order as **one BAG summary
fill plus one fill per leg**. `_write_fills`
(`src/services/intraday_sync_tws.py:306`) upserts all of them into
`live_executions` keyed by `ib_exec_id`, with no combo awareness.

The settled FlexQuery path does **not** persist the broker's BAG fill. Instead it
_synthesizes its own_ `combo_summary` row per multi-leg group
(`_synthesize_combo_summary`, `src/services/trade_sync_flexquery.py:592`; grouped
by `brokerageOrderID` in `_combo_groups`, line 164). That synthesized row:

- has a **different `ib_exec_id`** (derived from a leg, e.g.
  `0000wxyz.abcd1234.01.01`), so the exact-id purge never matches;
- has **`con_id = NULL`** and **`symbol = NULL`** in `raw`, so it shares no
  contract identity with the live BAG row (placeholder `con_id 400000001`);
- has an unrelated `brokerage_order_id` (e.g.
  `00aabbcc.00ddeeff.11223344.000`) that is **not present on the live row at
  all**.

So the live BAG summary and its settled equivalent share **no join key** —
neither id, nor con_id, nor symbol, nor order id. This is why the leg-strip and
book-event matchers cannot touch it, and why a naive `(account_id, con_id)`
match is impossible.

### The legs already reconcile; the summary is the leftover

The constituent legs _do_ settle and are already cleared by the shipped
leg-strip matcher (live `…02.01.01` → settled `…02.01`). Concretely, the two
**VIX** orphans above have **no live leg rows left** — their legs already
settled and were purged, leaving only the redundant summaries. The SPCX and MARA
summaries still have (or had) sibling legs at the same `exec_time`.

**Key framing:** the live BAG summary is a _display convenience_. FlexQuery is
authoritative and synthesizes its own summary. Once a combo's legs have settled,
the live BAG summary is pure redundancy and should be purged — we do **not** need
to positively match it to a specific settled row, only to establish that its
legs have settled.

### Root blocker: no order grouping key on `LiveExecution`

To tie a BAG summary to its legs we need a shared key. The only signal on the
current `LiveExecution` schema is `exec_time` (BAG and legs share a timestamp) —
fragile, because two combos on the same account can fill in the same second. The
broker fills _do_ carry `execution.permId` / `execution.orderId`, but
`_live_execution_values` (`src/services/intraday_sync_tws.py:284`) discards them
and `LiveExecution` (`src/models.py:887`) has no column for them. This is exactly
the gap **Fix C / U3** of the contract-parity plan already scopes:

> Add `perm_id` (and/or `ib_order_id`) so legs can be grouped to their BAG
> summary within a sync batch. Group key preference: `permId` (stable across the
> order lifecycle); fall back to `orderId` when `permId` is absent.

This plan should **land on top of Fix C**, reusing that key rather than adding a
parallel one.

---

## Options considered

| #   | Approach                                                                                                                                                                    | Precision | Needs Fix C order key | Fixes existing 4 | Notes                                                                             |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | --------------------- | ---------------- | --------------------------------------------------------------------------------- |
| 1   | **Leg-anchored purge** — group summary→legs by order key; purge the summary once all its legs are settled (absent from `live_executions` and present in `trade_executions`) | High      | **Yes**               | Yes              | Principled; no fuzzy contract match; recommended                                  |
| 2   | **Timestamp-batch purge** — group by `(account_id, exec_time)` instead of an order key                                                                                      | Medium    | No                    | Yes              | Ships without Fix C, but two same-second combos on one account collide; heuristic |
| 3   | **Match to settled `combo_summary`** — pair live BAG to FlexQuery's synthesized summary                                                                                     | Low       | Yes (still weak)      | Partial          | No shared key (con_id/symbol NULL, boid absent live); brittle even with order key |
| 4   | **Age/TTL purge** — drop BAG summaries older than N business days                                                                                                           | Low       | No                    | Yes              | Simplest; hides rather than reconciles; mislabels a genuinely slow settlement     |

Option 3 is a dead end for the same reason the shipped matchers skip this class —
there is nothing reliable to join on. Option 4 is the display band-aid from the
original options table, not a reconciliation. Options 1 and 2 differ only in the
grouping key.

---

## Recommended approach — Option 1 (leg-anchored purge, on Fix C's order key)

Once Fix C persists `perm_id` / `ib_order_id` on `LiveExecution`:

1. Extend `reconcile_orphaned_live_executions` with a **third matcher**,
   `_match_bag_summary`, that runs after leg-strip and book-event.
2. For an orphaned `sec_type == "BAG"` row, collect its **sibling legs** — other
   `live_executions` rows sharing its order key (`perm_id`, else `ib_order_id`).
3. Purge the summary **iff every sibling leg has left `live_executions`** (i.e.
   already settled/reconciled) **and** the order's legs are represented in
   `trade_executions` — proving the combo settled. A summary with legs still
   live is left for a later run (they reconcile first).
4. Carry any preemptive group tag on the summary onto the settled combo — prefer
   the FlexQuery `combo_summary` for that order when resolvable, else the
   settled legs' parent trade — reusing `carry_over_link_to_execution`
   (`src/services/group_link_carryover.py`). If no settled target is resolvable,
   drop the summary's live link only after confirming the group already holds the
   settled legs (as the shipped matchers do), so membership is never lost.

This keeps the reconciler's shape — a list of narrow, ordered matchers, each
deleting only rows whose settled fate is proven — and needs no fuzzy contract
matching.

### If Fix C is not imminent

Ship **Option 2** as an interim: identical logic, grouping by
`(account_id, exec_time)` instead of the order key, with an explicit guard that
refuses to purge when more than one distinct combo shares that timestamp on the
account (log and skip). This clears the current 4 safely (each is an
unambiguous single-combo timestamp) without waiting on the schema change, and is
superseded cleanly when Fix C lands.

---

## Implementation steps

1. **(Dependency) Fix C / U3** — add `perm_id` / `ib_order_id` (+ `exec_role`)
   to `LiveExecution` and capture them in `_live_execution_values`
   (`src/services/intraday_sync_tws.py:284`). Migration per repo convention
   (Alembic).
2. **Third matcher** — add `_match_bag_summary(session, live)` to
   `src/services/live_reconcile.py`, wired into the existing loop after
   `_match_book_event`. Return the resolved settled target (or a sentinel for
   "purge, membership already settled").
3. **Group-link handoff** — extend the reconcile loop so a BAG-summary match can
   carry its tag onto the resolved settled combo, or safely drop the live link
   when the group already holds the settled legs.
4. **One-off cleanup** — a follow-on Alembic data migration mirroring
   `alembic/versions/20260714002003_cleanup_orphaned_live_executions.py`, or
   simply rely on the next FlexQuery sync (which calls the reconciler) to clear
   the backlog.
5. **BAG detection at ingest (optional, from Fix C)** — once `exec_role` is set
   on live rows, the summary is identifiable by `exec_role == "combo_summary"`
   rather than `sec_type == "BAG"`, tightening the matcher.

---

## Verification

- **Dry-run against prod** (read-only, as used for the shipped reconciler): the
  new matcher must target exactly the 4 BAG orphans and leave every non-BAG row
  untouched. Confirm the two VIX summaries (no live legs, legs already settled)
  purge, and SPCX/MARA purge only after their legs have reconciled.
- **Transactional test with rollback** (mirror
  `scratchpad/migration_txn_test.py`): assert `live_executions` drops by 4, the
  SPCX(46)/MARA(35) group memberships survive via the settled combo, and
  `trade_group_live_executions` loses only the reconciled links.
- **Overlay P&L unchanged** — all 4 are realized `0`, so intraday totals must not
  move (unlike the leg-strip class, this is a pure display cleanup).

---

## Scope boundaries / non-goals

- **Not** matching a live BAG summary to a settled `combo_summary` by contract
  identity (Option 3) — no reliable key exists.
- **Not** persisting our own synthesized live summary, and **not** changing how
  FlexQuery synthesizes combo summaries.
- **Does not** block on displaying COMBO/LEG badges for still-unsettled combos —
  that is Fix C's UI concern; this plan only removes summaries _after_ settlement.

## Risks

- **Timestamp collision (Option 2 only):** two combos filling in the same second
  on one account would group together; mitigated by the single-combo guard and
  removed entirely once Fix C's order key lands.
- **Membership loss:** dropping a summary's live tag must never orphan a group
  assignment; the handoff must confirm the settled combo/legs are already in the
  group first, exactly as the shipped matchers do.
- **Coupling to Fix C:** if Fix C's key choice changes (`permId` vs `orderId`
  fallback), this matcher's grouping must track it; keep the grouping key in one
  helper.
