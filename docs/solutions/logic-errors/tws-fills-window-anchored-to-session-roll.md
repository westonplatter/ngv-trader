---
title: Intraday fills window anchored to the session roll discarded most executions
date: 2026-07-31
category: logic-errors
module: intraday_sync_tws
problem_type: logic_error
component: service_object
symptoms:
  - "Freshly-opened positions cannot be assigned to a trade group; + Assign appears to work but no chip ever renders"
  - "A position is visible in the positions table with no rows in either `trade_executions` or `live_executions`"
  - "An intraday sync keeps only a handful of the fills TWS offers and silently discards the rest"
  - "Day-session fills vanish from the overlay at 18:00 ET and do not reappear until FlexQuery settles them ~a day later"
root_cause: logic_error
resolution_type: code_fix
severity: high
tags:
  - ib-async
  - ibkr
  - tws
  - reqexecutions
  - intraday-overlay
  - lookback-window
  - trade-groups
  - silent-data-loss
related_components:
  - background_job
  - database
---

# Intraday fills window anchored to the session roll discarded most executions

## Problem

Freshly-opened positions could not be assigned to a trade group. The intraday TWS overlay bounded its fill ingest at the most recent 18:00 ET CME session roll, so a sync running shortly after the roll discarded nearly every fill TWS offered. The position existed with zero executions behind it — settled or live — and the assignment endpoint fans out over executions, so there was nothing to tag.

## Symptoms

- On the Positions page, clicking **+ Assign** appeared to succeed — no error, no toast — but the group chip never rendered. Reloading redrew "+ Assign" as if nothing had happened.
- Several same-day positions were affected at once; older positions assigned normally.
- The affected positions were visible in the positions table but had no rows in either `trade_executions` (settled) or `live_executions` (unsettled overlay).
- Some fills displayed a wall-clock date one day earlier than the trade date they settled under, which read as "settlement is running a day late."

## What Didn't Work

Three plausible explanations were wrong or incomplete, and the way each failed is the reusable part.

**Hypothesis 1 — "FlexQuery is T-1, just wait for tomorrow."** The settled-trade feed only publishes through the previous business day, and the affected positions were opened same-day. True, but not the whole story — and that is what made it dangerous. Accepting it would have closed the investigation with a real bug in place: the intraday overlay exists precisely to cover the T-1 gap, and it was failing to. A hypothesis that explains the symptom without explaining why the compensating mechanism didn't fire is not a diagnosis.

**Hypothesis 2 — "the TWS session roll ate them, and they are unrecoverable."** The theory was that `ib.reqExecutions()` only ever returns the current trading session's executions, so day-session fills were past TWS's reach. This produced a confident and completely wrong statement: _"there's no API call that will hand back those fills."_

**Where that claim came from — a docstring believed over the vendor docs.** It did not come from measurement or from IBKR. It came from this project's own `_fetch_fills` docstring, which asserted that `reqExecutions` "re-asks for all of _the current day's_ executions." An in-repo comment describing a third-party API is a secondary source with no update mechanism: the vendor cannot correct it, and it drifts silently. Session history confirms the claim was **assumed at introduction and never measured** — `ExecutionFilter` was grepped in the `ib_async` source at one point but never used to set a time window, and the actual temporal reach of `reqExecutions` was never probed. (session history)

Worse, the premise had already been stated explicitly and load-bearingly in an earlier session — that loosening the TWS window "would not have worked… our filter can only _reject_ what `reqExecutions` hands back." That thread resolved by a different route, so the belief was never falsified and was inherited forward as settled fact. (session history)

**What the docs actually said — the opposite.** IBKR's [Executions and Commissions](https://interactivebrokers.github.io/tws-api/executions_commissions.html) page states verbatim that "By default, only those executions occurring since midnight for that particular account will be delivered," that "If you want to request executions up to last 7 days, TWS's Trade Log setting _'Show trades for ...'_ must be adjusted to your requirement," and that "IB Gateway would be unable to change the Trade Log's settings, thus limited to only executions since midnight to be delivered." The reach is **TWS-side configuration**, not a protocol limit — and this deployment connects to TWS (port 7496), not IB Gateway (4001/4002), so the wider window was already available and simply unused.

**What settled it — an empirical probe, not more reasoning.** A throwaway read-only script connected with an unused client id, called `ib.reqExecutions()` with a default (empty) filter, and printed every fill returned, marking each KEEP/DROP against the sync's own `window_start`. The result was unambiguous: **TWS returned 72 fills spanning roughly a week; only 6 passed the filter and 66 were discarded by our own code.** Re-running with an explicit `ExecutionFilter(time=...)` set seven days back returned the _same_ 72, confirming the Trade Log setting — not the request — governs reach. That probe converted "IBKR won't give us the data" into "we are throwing the data away."

## Solution

Replace the session-roll _anchor_ with a rolling _duration_ in `src/services/intraday_sync_tws.py`.

Before — an anchor at the most recent 18:00 ET roll:

```python
MARKET_TZ = ZoneInfo("America/New_York")
SESSION_OPEN_HOUR_ET = 18

def session_start_utc(now: datetime | None = None) -> datetime:
    """UTC instant the current exchange trade date opened (most recent 18:00 ET)."""
    now = now or _now_utc()
    et_now = now.astimezone(MARKET_TZ)
    session_open = et_now.replace(hour=SESSION_OPEN_HOUR_ET, minute=0, second=0, microsecond=0)
    if et_now < session_open:
        session_open -= timedelta(days=1)
    return session_open.astimezone(timezone.utc)
```

After — a fixed rolling lookback (`src/services/intraday_sync_tws.py:54`, `:75`):

```python
FILLS_LOOKBACK_DAYS = 2

def fills_window_start(now: datetime | None = None) -> datetime:
    """Lower bound (UTC) for fills written to the overlay. ``now`` is for testability."""
    now = now or _now_utc()
    return now - timedelta(days=FILLS_LOOKBACK_DAYS)
```

The call site in `run_intraday_sync` reads `window_start = fills_window_start(now)` (`:583`); `_write_fills` applies it unchanged at `:486`. The `MARKET_TZ` / `SESSION_OPEN_HOUR_ET` constants and the now-unused `zoneinfo` import were deleted.

The misleading `_fetch_fills` docstring was rewritten to record what the vendor docs actually say: reach is governed by the TWS Trade Log setting up to 7 days, IB Gateway cannot change it, and **the practical bound is `FILLS_LOOKBACK_DAYS` applied by `_write_fills`, not by the request**. The constant carries the measurement inline so the next reader sees the 6-of-72 number without re-deriving it.

## Why This Works

**Root cause: an anchor was used where a duration was needed.** Because `window_start` was a fixed point on the clock rather than a span, the _effective_ lookback was a sawtooth — about 24 hours just before a roll, near zero just after. A sync running 35 minutes after the roll saw a 35-minute window and dropped the entire day session. The fill then had no home: it left the overlay at 18:00 ET and would not reappear until FlexQuery settled it roughly a day later.

The anchor was not arbitrary, which is why it survived review. It had been deliberately moved from ET midnight to the 18:00 ET roll so that evening fills were not mislabeled — an evening fill belongs to the next trade date. That reasoning is correct for **labeling** a fill's trade date and wrong for **bounding how much unsettled history to retain**; the two questions were conflated. Session history confirms a duration-based window was never proposed or rejected — it simply never came up, because the anchor was chosen to _mirror what `reqExecutions` was believed to offer_. The window was sized to a belief about the API rather than to the recovery requirement. (session history)

A retention window should be sized by how long the settled feed takes to catch up — about a day, so two days with margin — not by where the exchange draws its day boundary.

**Why widening is safe — settled data wins on both sides of the handoff.** Reaching back two days necessarily pulls in fills FlexQuery has already settled. That cannot corrupt the settled record, because two independent mechanisms enforce settled-wins:

- _Write path._ `run_intraday_sync` calls `_write_fills` then `_purge_settled` inside one `Session`, with a single `commit()` after both (`:612-630`). `_purge_settled` (`:556`) deletes every `live_executions` row whose `ib_exec_id` matches a `trade_executions` row, plus BAG/combo rows matched by identity via `_settled_combo_summaries` (`:518`) — same account, same instant, both BAG — carrying any trade-group link to the settled execution first. An already-settled fill is written and deleted in the same transaction; it is never visible to a reader.
- _Read path._ `_unsettled_live_executions` in `src/api/routers/trades.py:912` independently filters `LiveExecution.ib_exec_id.not_in(select(TradeExecution.ib_exec_id))`.

The window therefore only decides **how much unsettled tail is visible**. It cannot let TWS data override FlexQuery. That is the load-bearing argument for why the constant can be raised without a settled-data risk review — and it was never actually discussed when the purge was built, so it is recorded here. (session history)

**Verification against the live prod database.** Re-running the sync produced 36 fills written, **7 purged as already-settled**, ending at 29 live rows. The invariant — count of `live_executions` rows having a settled counterpart — was 0 before and 0 after. The `purged: 7` is the load-bearing evidence, not the final 0: it shows the settled-wins path actually _firing_ on real overlap, rather than the invariant holding vacuously. All previously-missing positions gained executions and became assignable.

**One caveat, documented rather than fixed.** The read-path dedup is plain `ib_exec_id` equality, so it does not cover combo **BAG summary** rows, whose live and settled ids come from different families and can never match. The read path still does not handle them. The write path does, but not through `_purge_settled` alone: its `_settled_combo_summaries` identity match only fires when a settled BAG row shares the same account _and the exact same instant_, which frequently misses. Covering the rest took a second mechanism — the `live_reconcile` Class C redundancy purge (PR #98), which itself later needed the fix in [the peer-summary deadlock learning](./bag-combo-summary-purge-deadlocks-on-peer-summaries.md). Widening the window exposes more rows to that asymmetry.

**A separate defect found and left unfixed.** `assign_positions` (`src/api/routers/trade_groups.py:634`) fans an assignment out to the position's constituent executions. When a position has zero of both kinds, the loop body never runs, `db.commit()` (`:720`) commits nothing, and the endpoint still returns its declared **HTTP 204**. The UI reloads, sees no membership, and redraws "+ Assign" — a silent no-op indistinguishable from success. This is what turned a data-window bug into an _invisible_ one. Suggested fix: return 409 naming the cause.

**A related non-bug worth recording.** CME's trade date rolls at 18:00 ET, so an evening fill belongs to the _next_ trade date. A UI showing local wall-clock time in one column while settlement status is governed by exchange trade date in another will make evening fills look like they settled a day late. Correct behavior, but it costs real debugging time when unrecognized.

## Prevention

**Never let an in-repo docstring be the authority on a third-party API's semantics.** The wrong turn traces to one sentence of our own prose about `reqExecutions`, believed over IBKR's published docs. When a comment makes a factual claim about vendor behavior it needs a citation to the vendor page; a claim without one is a hypothesis. When a diagnosis rests on "the API only returns X," open the vendor doc before writing the conclusion down.

**Distinguish an anchor from a duration when writing any retention or lookback window.** An anchor (most recent 18:00 ET, midnight, start of month) makes the effective span oscillate between full and zero depending on when the job runs. A duration (`now - timedelta(days=N)`) is constant. Use an anchor only when the semantics genuinely are "since the boundary" — labeling a trade date, computing a daily aggregate. When reviewing a time filter, ask: _what is the effective window if this job runs one minute after the anchor?_ If the answer is "one minute," it is the wrong primitive.

**Reach for a read-only empirical probe before reasoning further from source.** Three rounds of hypothesis produced a wrong answer; one short script produced the right one in a single run. The pattern: connect with an **unused client id** so the pooled session is untouched, call the API with the **widest/default filter**, print every record returned, and **mark each KEEP/DROP against the production code's own boundary**. That last step is what makes it diagnostic — it shows the delta between what you were given and what you kept. Then vary one input to confirm which side owns the limit.

**Treat a partially-correct explanation as unfinished.** When a system has a compensating mechanism for the condition you just diagnosed, the investigation is not done until you know why that mechanism didn't fire.

**Make no-op writes loud.** An endpoint that iterates a collection and returns 204 unconditionally reports success for an empty collection. Any endpoint whose effect depends on a non-empty fan-out should count rows touched and return 409/422 on zero, or return the count in the body. This bug was findable in minutes if the assign call had said "0 executions linked."

**Prove safety invariants by observing them fire, not by observing them hold.** `purged: 7` is stronger evidence than "0 duplicates found," because the zero could be vacuous. When verifying a dedup, precedence, or override rule, arrange for real overlap and confirm the mechanism ran.

## Operational Notes

- **Restart the jobs worker after changing sync code.** It caches `src.models` and `intraday_sync_tws` in memory and runs under the operator's `op run` session, so enqueuing a job after an edit just runs the old code. To validate without touching the running worker, invoke `run_intraday_sync` from a fresh process with its own unused client id. (session history)
- **Do not run `ruff format` on this file.** The repo is not ruff-formatted and sets no `line-length`, so formatting produces ~90–130 lines of pure churn. Lint with `uv run ruff check` instead. (session history)

## Related

- [ib_async reqExecutions returns fills stripped of their commission reports](../integration-issues/ib-async-req-executions-strips-commission-reports-2026-07-29.md) — same file and same function (`_fetch_fills`), different failure. That fix introduced the incorrect "current day's executions" docstring this bug traces to. Its `reqExecutions` → `ib.fills()` call ordering is load-bearing and must not be "simplified" while widening the window; its _Related Issues_ note about the ET-midnight → 18:00 ET trade-date boundary describes an intermediate state that the present learning supersedes.
- [Peer BAG combo summaries counted as siblings deadlocked the redundant-summary purge](./bag-combo-summary-purge-deadlocks-on-peer-summaries.md) — the write-path story for combo BAG summaries, continued. `_purge_settled`'s identity match is not the whole handoff; the `live_reconcile` Class C purge covers the rest, and its "no live siblings" gate deadlocked peer summaries from partial fills against each other. The rolling window documented here is what turned that deadlock from a one-run annoyance into a permanently stuck row.
- [Intraday TWS overlay](../../core/intraday-tws-overlay.md) — the overlay's sync rules and live/settled two-tier model.
- PR #94 (`feat: trade-booking improvements for unsettled fills and tagging`) — origin of both the corrected `_fetch_fills` and the 18:00 ET anchor replaced here.
- PR #52 (`feat(intraday): live TWS overlay for current-state P&L on FlexQuery positions`) — original overlay; introduced the day-window filter concept.
- PR #53 (`feat(positions): associate real-time TWS positions with a trade group (execution-level)`) — origin of the `assign_positions` execution fan-out that silently returns 204.
