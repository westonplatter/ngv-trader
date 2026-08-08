---
title: Peer BAG combo summaries counted as siblings deadlocked the redundant-summary purge
date: 2026-08-07
category: logic-errors
module: live_reconcile
problem_type: logic_error
component: service_object
symptoms:
  - "Two phantom `unsettled` COMBO Roll BAG rows persist in /trades alongside the same combo's already-settled `filled` rows"
  - "The stale live rows never clear, no matter how many intraday or FlexQuery syncs run"
  - "Only multi-partial combo fills are affected; single-execution combos purge normally"
  - "The settled combo summary and its option legs render correctly, so the data looks duplicated rather than missing"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - ibkr
  - tws
  - combo
  - bag-summary
  - live-executions
  - reconciliation
  - settle-handoff
  - partial-fills
related_components:
  - background_job
  - database
---

# Peer BAG combo summaries counted as siblings deadlocked the redundant-summary purge

## Problem

A combo order that fills in **several partial executions** leaves TWS emitting one BAG combo-summary row _per partial_, all sharing the order's `permId`. The Class C purge in `src/services/live_reconcile.py` gates on `_has_live_siblings` (`:199`) — "are this combo's legs still unsettled?" — but the implementation counted **any** other `live_executions` row sharing the order key, peer summaries included. Each summary saw the other still present, concluded siblings remained, and deferred. Neither could ever reach zero, because the only sibling each had was the other.

A mutual deadlock, not a missed match. The rows lingered indefinitely.

## Symptoms

- Two rows with status `unsettled` for one SPCX option-spread roll persisted in `/trades` long after the settled trades had loaded from FlexQuery.
- They shadowed the same combo's correct settled rows — a `filled` `COMBO Roll BAG BUY 1 @9.60` summary plus its four settled option legs — so the roll appeared twice.
- Re-running the sync did not clear them. The state was stable, not transient.
- A different roll on the same account one second earlier, which produced a **single** BAG summary, reconciled correctly and displayed only as `filled`. That contrast is what localized the bug to the multi-summary case rather than to Class C as a whole.

## What Didn't Work

**Hypothesis 1 — "same bug as the fills-window learning."** The obvious starting point was [`tws-fills-window-anchored-to-session-roll.md`](./tws-fills-window-anchored-to-session-roll.md), which flags a matching-sounding caveat: the read-path dedup is plain `ib_exec_id` equality, so "it does not cover combo **BAG summary** rows, whose live and settled ids come from different families and can never match." Shape matches; diagnosis doesn't. That caveat is about the _read_ path. The _write_-path machinery — `_purge_settled` → `_settled_combo_summaries` (`src/services/intraday_sync_tws.py:518`), plus the later Class C matcher in `live_reconcile.py` — was built specifically to handle BAG summaries. The compensating mechanism existed and should have fired. That doc's own Prevention section says the investigation is not done until you know why; it applied again, to itself.

**Hypothesis 2 — "the timestamps disagree."** A background research subagent, reasoning from code structure, concluded the failure was a timestamp mismatch: both `_settled_legs_at` (`live_reconcile.py:228`) and `_settled_combo_summaries` require exact `executed_at` equality, and on a multi-leg roll TWS and FlexQuery would disagree on the instant. Superficially strong — the settled BAG summary really is one second earlier than the live rows.

The real rows refuted it. `_settled_legs_at` found **4 settled legs at exactly the live rows' timestamp**. The timestamp match was fine; the sibling gate was the blocker. Reasoning from code structure produced a plausible, specific, wrong cause; one read-only query ended it.

## Solution

Two changes in `src/services/live_reconcile.py`.

Add a SQL mirror of the existing Python predicate `_is_bag_summary` (`:168`):

```python
def _bag_summary_clause():
    """SQL form of ``_is_bag_summary`` — keep the two in step when either changes."""
    return or_(
        LiveExecution.exec_role == "combo_summary",
        func.upper(func.trim(func.coalesce(LiveExecution.sec_type, ""))) == "BAG",
    )
```

Exclude peer summaries from the sibling count in `_has_live_siblings` (`:199`):

```python
    remaining = session.execute(
        select(func.count())
        .select_from(LiveExecution)
        .where(column == value, LiveExecution.id != live.id, ~_bag_summary_clause())
    ).scalar_one()
    return remaining > 0
```

Docstrings on `_has_live_siblings` and the module's Class C paragraph were updated to say the gate counts **legs**, not rows, and to record why.

Deliberately not done:

- **No manual DB cleanup.** The stale rows were left in place. `reconcile_orphaned_live_executions` is idempotent and runs from both `src/services/intraday_sync_tws.py:628` and `src/services/trade_sync_flexquery.py:560`, so they clear on the next sync of either kind. The project forbids ad-hoc DB mutation — migrations only.
- **`_settled_combo_summaries` untouched.** It retains a related exact-timestamp-equality constraint (`intraday_sync_tws.py:545`). Out of scope for this fix.

Validation: `uv run ruff check src/services/live_reconcile.py` clean; `uv run python scripts/check.py` passes for `src.services.live_reconcile`, `src.services.intraday_sync_tws`, `src.services.trade_sync_flexquery`. (No pyright config exists in this repo — no `pyrightconfig.json`, no pyright in `pyproject.toml` or `Taskfile.yaml` — despite AGENTS.md calling for it.)

## Why This Works

`_has_live_siblings` answers "have this combo's legs settled yet?" A live leg only leaves `live_executions` by settling — via the exact-id purge, or one of the id-divergence matchers (Class A leg-strip, Class B book event) — so "no legs left" is valid proof. A **peer summary** is not a leg and is never evidence that a leg is outstanding. Excluding peers restores the predicate to the question it was written to answer.

**The premise was never wrong, only incomplete.** The design rationale recorded when Class C shipped in PR #98 was one sentence: _a live leg only leaves `live_executions` by settling, so "no sibling shares the order key" is the proof the combo settled._ That argument reasons exclusively about legs. It is valid only if the sole _other_ rows under an order key are legs — i.e. exactly one BAG summary per order. Peer summaries appear nowhere in the design, the plan doc, or the PR write-up; the partial-fill case was never raised and ruled out, it simply never came up. (session history)

Note the failure direction. The designer _did_ anticipate the sibling count admitting **false positives** — a summary arriving with no legs in the batch would satisfy the gate vacuously — and added `_settled_legs_at` as a corroborating guard against exactly that. The mirror-image failure, a **false negative** where a non-leg row inflates the count and blocks a legitimate purge, was not considered. One direction of the gate was guarded; the other was not. (session history)

That corroborating guard is why the purge does not become vacuous now that peers stop gating it: `_match_bag_summary` (`:249`) still requires `_settled_legs_at` to return a non-empty list, so a summary with no settled legs behind it cannot purge early. Both peers here carry the same `permId`, and `_order_group_key` prefers `permId` over `orderId`, so both collapse onto one key — which is what put them in each other's sibling count.

**Why the rows were permanently stuck rather than briefly wrong.** The TWS fills window is a rolling two-day lookback (PR #95), and `reconcile_orphaned_live_executions` was wired into the intraday path as well as the FlexQuery path (PR #100). So every intraday sync faithfully re-writes these summaries, and a purge gate that declines to retire them re-fails on each pass. A row Class C won't retire is not missed once — it is re-asserted forever. (session history)

**Verified with a read-only old-vs-new diff.** The natural check — run `reconcile_orphaned_live_executions` in a transaction and roll back, the house convention for this module — was blocked by the harness permission classifier, because the function issues DELETEs even when rolled back. The pivot: every Class C predicate (`_is_bag_summary`, `_order_group_key`, `_has_live_siblings`, `_settled_legs_at`) is pure SELECT, so a read-only script can **import the real predicates and evaluate old rule vs new rule side by side** over every live BAG summary, with a locally re-implemented copy of the _old_ rule for comparison.

| Live row                             | settled legs at ts | OLD     | NEW                 |
| ------------------------------------ | ------------------ | ------- | ------------------- |
| id=710 qty 2 @1.92 (perm `8888888`)  | 4                  | blocked | **purges**          |
| id=713 qty 1 @1.92 (perm `8888888`)  | 4                  | blocked | **purges**          |
| id=701 qty 2 @0.225 (perm `7777777`) | 0                  | blocked | blocked (unchanged) |

Row 701 is the **control**: a genuinely still-unsettled combo that must not purge. It stayed blocked under both rules, double-guarded by the sibling check and the `settled_legs == 0` corroboration. The control is what makes the diff meaningful — without it you have only confirmed the new rule fires, not that it fires _selectively_.

Settled-wins is unaffected. This change only narrows which live rows are eligible for deletion; it adds no path by which TWS data can override FlexQuery.

## Prevention

**A "no siblings left" termination condition must exclude peers of the same kind as the row being evaluated.** Otherwise members of a same-kind cohort mutually block each other and the gate never opens for any of them. This is a general shape, not a BAG-summary quirk: any "wait until all my related rows are gone" predicate deadlocks the moment the cohort can contain more than one of _itself_. When writing or reviewing one, ask **what happens when there are two of these?** Partial fills, retries, and batch splits are the usual ways a silent "there is exactly one" assumption breaks.

**Validate a cohort-sensitive predicate against a sample containing more than one member.** The original Class C change was dry-run against prod and confirmed to target _one_ row out of 21 live rows — correctly, for that row. The multi-summary shape was simply never in the sample, so the single-instance test could not have caught this no matter how carefully it was read. (session history) A dry run that resolves **two or more** summary rows is the regression check this class of change needs; "it did the right thing for the one case I had" is not coverage of a rule about cohorts.

**When you guard one failure direction of a gate, ask what the opposite direction looks like.** `_settled_legs_at` was added specifically to stop false-positive purges. The false-negative case — something inflating the count and blocking a legitimate purge — is the same predicate read backwards, and it went unexamined. Predicates that gate a destructive action get scrutinized for "does it fire when it shouldn't"; they need the same scrutiny for "does it fail to fire when it should," because that failure is silent and permanent rather than loud.

**Pair a Python predicate with its SQL mirror explicitly, in the docstring.** `_is_bag_summary` evaluates in-process; `_bag_summary_clause` must evaluate the same concept inside a query. Divergence between them is silent — no type error, no test failure, just a filter that quietly stops matching a subset. The docstring naming the counterpart is the only thing that survives a future edit to either one.

**Verify a change to a delete/purge predicate with a read-only old-vs-new comparison over real rows, including a control that must not change.** Pure-SELECT predicates can be imported and evaluated directly even when the enclosing function cannot be run — re-implement the old rule locally and diff the two verdicts row by row. This also routes around permission classifiers that (correctly) refuse to run a function containing DELETEs.

**A prior learning doc describing a similar-shaped failure is a hypothesis, not a diagnosis.** Match on mechanism, not on symptom shape. And when the system has a compensating mechanism for the condition you just diagnosed, keep going until you know why it didn't fire.

**Reasoning from code structure yields plausible-but-wrong causes; query the real rows.** The timestamp-mismatch theory was internally consistent, cited real constraints, and matched an observable one-second discrepancy. One `SELECT` against the actual live and settled rows killed it in a single step.

## Operational Notes

- **Restart the jobs worker after changing sync code.** It caches `live_reconcile` and `intraday_sync_tws` in memory, so enqueuing a job after an edit just re-runs the old code and the rows appear not to clear. Already recorded in the fills-window learning; it bit again here.

## Related

- [Intraday fills window anchored to the session roll discarded most executions](./tws-fills-window-anchored-to-session-roll.md) — the adjacent fix that made this bug chronic rather than transient: a rolling `FILLS_LOOKBACK_DAYS` window means TWS re-reports the same BAG summaries for days, so a deadlocked purge resurrects identical phantom rows on every sync instead of letting them age out. Its "One caveat, documented rather than fixed" paragraph predates the Class C purge and now understates the write path.
- [ib_async reqExecutions returns fills stripped of their commission reports](../integration-issues/ib-async-req-executions-strips-commission-reports-2026-07-29.md) — its _Related Issues_ "Combo settle handoff" note is the earliest statement of the asymmetry this whole class rests on: TWS books a combo's BAG summary under an id family its legs do not share, while FlexQuery synthesizes the settled summary _from_ the legs, so no id-equality purge can ever retire the live row.
- [Intraday TWS overlay](../../core/intraday-tws-overlay.md) — current-state description of the three reconcile classes. Its `bag_summary` row and "No live siblings left" paragraph are the prose this fix supersedes; both should read "no live _leg_".
- PR #98 (`fix(trades): purge redundant live BAG summaries once their combo settles`) — introduced the Class C matcher, `_is_bag_summary`, `_match_bag_summary`, and the `_has_live_siblings` gate this fix narrows.
- PR #93 (`feat: Trade booking refinements: reconcile orphaned fills, tagging/trades UI, jobs params`) — introduced `src/services/live_reconcile.py` with Classes A (leg-strip) and B (book events).
- PR #100 (`feat(trades): bring unsettled TWS fills to display parity with settled rows`) — wired `reconcile_orphaned_live_executions` into the intraday path, which is what makes an unretired row recur on every sync.
