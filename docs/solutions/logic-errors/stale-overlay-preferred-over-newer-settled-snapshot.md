---
title: A stale live overlay outranked a newer settled snapshot in three readers
date: 2026-08-29
category: logic-errors
module: intraday_overlay
problem_type: logic_error
component: api_router
symptoms:
  - "A position closed days ago still renders as held, with a Trade Group chip and P&L"
  - "On a Saturday the app serves Tuesday's numbers while Friday's settled snapshot sits unused"
  - "A freshness badge reads `stale 11:09 PM` on a capture that is four days old"
  - "Cost basis on a settled-backed option or futures row is 100x or 1000x too small"
  - "Fixing one page leaves another page showing the same stale data"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - intraday-overlay
  - flexquery
  - tws
  - staleness
  - precedence
  - cost-basis
  - units
  - plan-requirements
related_components:
  - api_router
  - service_object
  - frontend
---

# A stale live overlay outranked a newer settled snapshot in three readers

## Problem

The intraday overlay layers live TWS state over the settled FlexQuery snapshot.
`is_live_stale()` correctly identified an overlay older than the snapshot behind
it — and then nothing acted on the answer. Every reader took `position`,
`avg_cost`, and `source` from the live row whenever one existed, using the flag
only to set a display badge. A Saturday request therefore answered from a Tuesday
capture while Friday's settled import sat unused, on the majority of rows.

## Symptoms

- Positions closed days earlier rendered as held, with group chips and P&L.
- The freshness badge printed a bare time, so a four-day-old capture read as
  tonight — and it sat beside an "As of" column showing the settled date, which
  was correct and current. The misleading field had no date; the harmless one did.
- Fixing the Positions page left the Strategies page showing the same stale data.
- Separately, settled-backed contract rows reported cost basis 100x/1000x small.

## What Didn't Work

**The plan requirement that protected the bug.** The implementation plan carried:

> **R7.** Existing `is_live_stale` behavior for rows that have both a live and a
> settled row is unchanged.

That path was assumed correct and never tested, and R7 turned the assumption into
a constraint. It covered the majority of rows — the fix shipped against the
minority (live rows with no settled counterpart) and declared success.

**Worse, R7 suppressed its own fix.** When a later pass did change that path, an
existing staleness test failed. The failure was read as "I violated R7" and the
old behavior was restored. The test was reporting that the model had changed and
the group-level flag needed updating; it was interpreted as a regression. The
same test failed again after the real fix, for the same true reason, and was
correctly acted on the second time.

**"Fixed" was reported twice while a second reader still had the bug.** The
defect existed independently in `list_positions`, in `merge_positions`, and in the
live-only branch. Each was found separately by looking at a screenshot of a
different page. After the second, the third was _flagged as suspicious and a
question was asked_ rather than checked — and the user hit it before the answer
came back.

## Solution

**Make the flag gate the data.** `is_live_stale` now decides which source
supplies `position`, `avg_cost`, and `source`. A stale overlay is superseded data
and loses to the snapshot; the flag survives only so the UI can say a capture
exists and how old it is. The row is never dropped — a held position stays
visible with settled numbers.

**Normalize `avg_cost` at the read boundary.** The fallback could not ship alone.
The two sources store the field in different units by design: TWS reports it
already multiplied out, FlexQuery's `costBasisPrice` is per-unit. Every consumer
computes `qty·avg_cost` and reads dollars. Nine settled-backed rows were already
wrong; falling back without normalizing would have spread that to 62.
`normalize_settled_avg_cost` scales the settled value up, leaving the stored
column matching the raw IBKR report.

**Pin the rule at the shared merge, not at each call site.** Call sites are
exactly what kept getting missed one at a time.

**Date-qualify the badge** whenever the timestamp is not from today.

## Why This Works

**A flag that only labels is indistinguishable from a flag that acts, during
review.** `is_live_stale` was computed, returned in the response, rendered in the
UI, and covered by tests asserting it was `true` at the right times. Every one of
those signals said "staleness is handled." None of them checked that anything
_changed_ as a result. When adding a freshness or validity flag, the reviewable
question is not "is it computed correctly" but "what does it gate."

**Precedence must live where the sources meet, not where they are consumed.**
Three readers each independently re-implemented "prefer live," so the rule had
three chances to be wrong and was wrong in all three. Pinning it at
`merge_positions` with a test means a fourth reader inherits it.

**The strict `>` on the watermark needs no session calendar.** No venue's trade
date runs more than one day ahead of the Chicago calendar date — CME rolls
17:00 CT, Blue Ocean ATS runs 20:00–04:00 ET, ASX and Tokyo sit one day forward.
That single bound covers every instrument, and errs toward keeping a still-fresh
row rather than deleting one. An earlier design split the rule by `sec_type`;
measurement killed it — US equities traded on Blue Ocean and a foreign listing on
ASX both carry next-day trade dates, so the asset-class proxy misfiles exactly
the rows it was introduced to handle.

**Verify a units change against the vendor's own number, not against reasoning.**
IBKR publishes `fifo_pnl_unrealized` per row. The identity
`qty·mark·multiplier − qty·avg_cost == fifo_pnl_unrealized` turned an argument
about conventions into a measurement: 76/76 rows agreed after the fix, and 62/76
would have failed before it. Same discipline as the read-only probe in
[the fills-window learning](./tws-fills-window-anchored-to-session-roll.md) —
when reasoning about a third-party convention, find the number the vendor already
computed and check against it.

## Prevention

**Treat "preserve existing behavior" in a plan as an assumption, not a
constraint.** A requirement to leave a path unchanged is a claim that the path is
correct. If it has not been tested, it is a hypothesis wearing a requirement's
clothes — and it will be cited to reject the evidence that contradicts it. Either
test it before writing it down, or write it down as an assumption.

**When a test fails against a change you believe in, ask which is wrong before
reverting.** A failing test that encodes the old model looks identical to a
regression. The distinguishing question is whether the assertion still describes
behavior you want. Here the answer was no, twice, and reverting the first time
cost a full extra cycle.

**When you find a bug in a second reader, go looking for the third before
reporting done.** Duplicated precedence logic does not come in twos by nature; it
comes in as many copies as there are consumers. Grep for the shape, not the file.

**A staleness or freshness indicator must be legible at the ages it will actually
reach.** This one was refreshed manually and had no source to reconnect to over a
weekend, so multi-day gaps were routine — and it rendered a bare clock time,
which is least readable exactly when staleness matters most.

## Related

- [Intraday TWS overlay](../../core/intraday-tws-overlay.md) — current-state docs
  for the overlay's invalidation rules, precedence, and cost-basis convention.
- [Intraday fills window anchored to the session roll](./tws-fills-window-anchored-to-session-roll.md)
  — the executions half of the same settled-wins story, and the source of the
  anchor-vs-duration rule. The watermark here is a sanctioned anchor use: it
  labels which trade date a capture belongs to, not how much history to retain.
- [Position trade-group chips included closed lots](./position-trade-group-chips-included-closed-lots.md)
  — the same "attribution computed from the wrong set" shape on the group side.
