---
title: One stale live capture net-closed every position opened after it
date: 2026-08-29
category: logic-errors
module: intraday_overlay
problem_type: logic_error
component: service_object
symptoms:
  - "A position is missing from a Trade Group's Open Positions while the Positions page shows it"
  - "The opening execution is correctly tagged to the group, and the settled snapshot holds the position"
  - "Two screens reading the same tables disagree about whether a holding exists"
  - "A group's unrealized P&L silently omits a leg opened after the last TWS refresh"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - intraday-overlay
  - staleness
  - precedence
  - trade-groups
  - inference
  - scoping
related_components:
  - service_object
  - api_router
---

# One stale live capture net-closed every position opened after it

## Problem

`merge_positions` drops a settled position when its account has live data, on the
reasoning that a synced account which omits the instrument has netted it flat.
The account set was every account appearing in `live_rows`, with no check on how
old those rows were.

A four-day-old TWS capture covering **one** contract was therefore enough to mark
its whole account "synced". Every other holding in that account — including a
short opened two days _after_ the capture — was absent from the overlay, read as
net-closed, and dropped. The position existed in the settled snapshot with the
correct quantity, and its opening execution was correctly linked to the group.

## Symptoms

- A group's Open Positions panel omitted a held short; `GET /positions` listed it.
- Every upstream check passed, which is what made it hard: the execution was in
  `trade_group_executions`, the `positions` row had `position = -1`, the pair was
  in `account_con_pairs`, and the endpoint returned the execution. Only the
  overlay's own output was short a row.
- The group's unrealized total was wrong by exactly that leg, with no error.

## Root Cause

Two rules that both consult the same watermark, only one of which applied it.

`load_overlay_context` filters `live_rows` with `is_overlay_superseded` — but
deliberately only for rows with **no** settled counterpart, because a row that
has both is handled per-row by `is_live_stale` and dropping it would hide a held
position. Correct on its own terms.

The stale row in question _had_ a settled counterpart. So it survived the filter,
as designed, was correctly rendered from settled numbers by the per-row rule —
and then its mere presence in the surviving `live_rows` list made its account
count as live-synced. The per-row staleness verdict never propagated to the
account-level inference computed from the same list.

`GET /positions` was unaffected because it has no net-closed path at all: it emits
every settled row unconditionally and applies `is_overlay_superseded` only to
live-only rows. The bug lived exclusively in the shared merge helper — the one
the group endpoints use and the portfolio endpoint doesn't.

**Pair-scoping amplified it.** The group endpoint merges only the group's
`(account_id, con_id)` pairs, so it saw exactly one of the account's live rows;
portfolio-wide there were many, several of them fresh. The narrower the scope,
the likelier the sole surviving live row is a stale one — so the defect surfaces
on group screens first and can look like a tagging problem.

## Solution

Build the account set from non-superseded captures only:

```python
live_accounts = {
    r.account_id for r in live_rows
    if not is_overlay_superseded(r.fetched_at, account_as_of.get(r.account_id))
}
```

`account_as_of` was already computed in `load_overlay_context` (account-wide, not
pair-scoped, for exactly this class of reason) but stayed local to the loader. It
now rides on `OverlayContext` so every caller of the merge passes it. It defaults
to `{}` — prior behavior — only for callers with no settled snapshot to compare
against.

Regression tests cover both directions: a superseded capture must not net-close a
position opened after it, and a current capture must still net-close an
instrument it omits.

## Why This Works

**A staleness verdict has to travel with the row into every use of it.** The
prior fix ([stale overlay outranked a newer settled
snapshot](./stale-overlay-preferred-over-newer-settled-snapshot.md)) established
that `is_live_stale` gates the data and not just the label, and it does — for the
row's _own_ fields. What it did not cover is the row being used as **evidence
about other rows**. Those are separate questions with the same input, and
answering one does not answer the other.

**Ask what a row is being used as, not just whether it is displayed correctly.**
The three ways this codebase consumes a live row are: as its own numbers, as
proof a position still exists, and as proof that _absent_ positions no longer
exist. The third is the only one that is not per-row, and it is the only one that
had no staleness gate. Absence-as-evidence is always the weakest inference in a
system with two data sources, because absence has at least two causes.

**Watermarks are account facts and must be computed account-wide.** Every
scope-narrowing operation — pair filters, per-group slicing — is a chance to
recompute an account-level fact from a subset and get a different answer than the
next screen. Keeping `account_as_of` on the shared context, sliced by nobody, is
what makes the group and portfolio views agree by construction rather than by
review.

## Prevention

**When a filter carves out an exception, check what still consumes the rows it
let through.** The `settled_keys` carve-out in `load_overlay_context` was right,
and it was documented, and it created a category of row that is simultaneously
"kept" and "not to be trusted". Anything downstream that treats the list as
uniformly trustworthy inherits a bug. A carve-out is a fork in the data's meaning,
so it needs a note at the _consumers_, not only at the filter.

**Two screens disagreeing about the same table is a merge bug until proven
otherwise.** Both read `positions` and `live_positions`; both got the same rows.
Diffing the two read paths found this in one pass, and would have found it faster
than working forward from the tagging layer — where every check passes.

**Prefer a shared helper's inference over a hand-rolled one — but audit the
inferences it makes that the hand-rolled path never had.** `merge_positions`
exists so precedence lives in one place, which is right. The cost is that it also
centralizes a _stronger_ inference (net-closing) than `GET /positions` performs at
all, so it can be wrong in a way its callers can neither see nor override.

## Related

- [Intraday TWS overlay](../../core/intraday-tws-overlay.md) — the three
  invalidation mechanisms, and which of them is per-row.
- [A stale live overlay outranked a newer settled snapshot in three readers](./stale-overlay-preferred-over-newer-settled-snapshot.md)
  — the same watermark, applied to the row's own fields. This is its blind spot.
- [Position trade-group chips included closed lots](./position-trade-group-chips-included-closed-lots.md)
  — the same "attribution computed from the wrong set" shape.
