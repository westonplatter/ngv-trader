---
topics: ["live-data", "tws", "positions", "fills", "intraday", "market-data"]
code_dirs_or_files:
  [
    "src/services/intraday_sync_tws.py",
    "src/services/intraday_overlay.py",
    "src/services/live_reconcile.py",
    "src/services/group_link_carryover.py",
  ]
description: Live TWS overlay for intraday positions — marks, fills, settlement handoff, orphan reconciliation, and read-time merge over FlexQuery snapshots.
---

# Intraday TWS Overlay

Current-state documentation for the live, current-state P&L overlay sourced from
TWS, layered on top of the settled FlexQuery snapshot.

## Purpose

FlexQuery is the canonical settled record but lands T-1: the `positions` table
holds yesterday's EOD quantities/marks, so the TradeGroup and Positions views
are stale intraday. This overlay adds an **optional, on-demand live layer** from
a TWS/Gateway session — current quantity, blended cost, live marks, and today's
realized — **without ever writing the FlexQuery tables**. If no TWS session is
available, the views silently degrade to settled values.

The authoritative current state is `ib.positions()` (current quantity + blended
average cost for every held contract, including ones opened today), so the four
intraday mutation cases — opened / added / reduced / net-closed-or-flipped — all
fall out without lot arithmetic. Fills drive _realized_ attribution only, never
quantity.

## Data model (separate from FlexQuery)

Three additive tables hold the overlay; the FlexQuery `positions` /
`trade_executions` tables are never touched.

| Table             | Holds                                                                      | Key                                    |
| ----------------- | -------------------------------------------------------------------------- | -------------------------------------- |
| `live_positions`  | current TWS qty + blended `avg_cost` per holding                           | unique `(account_id, con_id)`          |
| `latest_quote`    | live marks (bid/ask/last/close + selected `mark`) for any sec type         | `con_id` (supplied, not generated)     |
| `live_executions` | recent unsettled fills with `realized_pnl`, expiry, order key, `exec_role` | unique `ib_exec_id` (dedup vs settled) |

`latest_quote` is sec-type-agnostic (FUT/FOP/STK/OPT) and intentionally **not**
FK'd to the futures-only `contracts` table — distinct from `latest_futures*`
(which the term-structure feature continues to own; see [security-data.md](../security-data.md)).

## Sync flow

One manual-triggered job does all three fetches in a single IB session.

```text
"Refresh Live (TWS)" button ─► POST /positions/sync/intraday-tws
   ─► enqueue Job(intraday.sync.tws)
   ─► worker: handle_intraday_sync_tws → run_intraday_sync(engine, ib)
        ib.positions()          → live_positions  (replace per account scope)
        qualifyContracts + reqTickers(held) → latest_quote (mark rule)
        reqExecutions() + ib.fills() (rolling lookback)
                                → live_executions, purge settled by ib_exec_id
```

Service: `src/services/intraday_sync_tws.py` (`run_intraday_sync`). Job type
`intraday.sync.tws`; handler in `src/workers/jobs.py`; see [workers.md](../workers.md).

Key rules (defined once in the service):

- **Mark selection:** `last` if present; else midpoint `(bid+ask)/2` when both
  sides exist; else `close`; else null (degrades to the snapshot mark).
- **Fills window:** a rolling lookback of `FILLS_LOOKBACK_DAYS` (2) ending now —
  not an anchor at a session or calendar boundary. An anchor makes the effective
  window oscillate between ~full and ~zero depending on when the sync runs, which
  silently dropped day-session fills. Reaching back past the current trade date is
  safe because settled data wins (see **Settle handoff**).
- **Exchange qualification:** `ib.positions()` returns contracts without an
  exchange, which `reqTickers` rejects. Held contracts are run through
  `qualifyContracts` first (real exchange for futures/index options; SMART
  fallback for equity-style) before requesting marks.
- **Replace semantics:** `live_positions` rows for the fetched accounts are
  cleared and re-inserted each run, so net-closed positions disappear.
- **Settle handoff (executions):** a live fill whose `ib_exec_id` already exists
  in settled `trade_executions` is purged; the read-time merge also drops such
  duplicates. Tomorrow's FlexQuery sync ingests today's fills as settled — no
  double count. This is load-bearing, not just a dedup nicety: because the fills
  window reaches back past settlement, `_purge_settled` (write path, same
  transaction) and the read-path filter are what keep FlexQuery authoritative.
  See [the fills-window learning](../solutions/logic-errors/tws-fills-window-anchored-to-session-roll.md).
- **Settle handoff (positions):** the mirror of the above, and it runs from the
  _FlexQuery_ side rather than here — see **Overlay invalidation** below. Held
  separately because positions have no identity to match on: a closed position is
  simply _absent_ from the snapshot, so disposal is by watermark and fill history
  instead of by id.
- **Combo roles:** the feed delivers a combo order as one `BAG` summary fill
  plus one fill per leg. Each fill stores its order key (`ib_perm_id`, falling
  back to `ib_order_id`) and `_exec_roles_by_exec_id` resolves `exec_role` over
  the whole batch — within an order group the BAG becomes `combo_summary` and
  its siblings `leg`. Mirrors FlexQuery's `_combo_groups` ≥2-distinct-conid
  guard, so a lone BAG or single-leg order stays `standalone`. Roles are
  recomputed per batch, keeping the upsert idempotent on `ib_exec_id`.

## Overlay invalidation — settled data wins

The overlay is refreshed by hand, so a capture routinely outlives the settled
snapshot it was layered over. Two mechanisms keep it from being presented as
current, and both treat the FlexQuery snapshot as authoritative.

**Write-time purge.** `_purge_superseded_live_positions` runs inside
`sync_flex_positions` — so the _settled_ import is the trigger and the overlay
expires with no TWS connection. Two independent signals:

| Signal         | Rule                                                           | Covers                                                                                                                                                              |
| -------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Watermark      | `as_of_date > CT_date(fetched_at)`                             | Anything the snapshot postdates — including a contract that left the book by **expiry**, which produces no closing fill and so is invisible to any fill-based check |
| Net-zero fills | ≥1 canonical fill, netting flat, latest postdating the capture | A same-day close, without waiting for the watermark to advance                                                                                                      |

The `≥1 fill` guard is load-bearing: an empty fill history means transferred-in
lots or fills predating the sync window, not a close.

The comparison is **strict** because no venue's trade date runs more than one day
ahead of the Chicago calendar date (CME rolls 17:00 CT; Blue Ocean ATS runs
20:00–04:00 ET; ASX and Tokyo sit one day forward). That single bound removes any
need for a per-venue session calendar, and errs toward keeping a still-fresh row.

**Read-time precedence.** `is_live_stale` gates the _data_, not just the label. A
stale overlay supplies neither quantity, cost, nor `source`; the snapshot does,
and the flag survives only so the UI can say a capture exists and how old it is.
The row is never dropped — a held position stays visible with settled numbers.

Both read paths apply this, and both had to be fixed independently. See
[the stale-overlay learning](../solutions/logic-errors/stale-overlay-preferred-over-newer-settled-snapshot.md).

## Read-time merge

`src/services/intraday_overlay.py` holds pure, DB-free merge/PnL helpers:

- `merge_positions(flex_rows, live_rows, quotes, magnifiers, metrics)` — prefer
  live qty/cost/mark **when the overlay is fresh**, else the FlexQuery row; drop
  net-closed; surface opened-since-snapshot rows.
- `is_overlay_superseded` / `superseded_cutoff` — the row-wise and set-based forms
  of the watermark, pinned equal by test so the write and read paths cannot drift.
- `mark_if_fresh` — ages out a futures/FOP mark after an hour. Equity marks are
  not age-capped: a stock's last print is its close.
- `intraday_unrealized_total`, `marks_as_of`, `dedupe_live_realized`.
- `compute_unrealized` / `parse_multiplier` — the shared cost-basis convention.

Every consumer loads its rows through `load_overlay_context()` in
`src/services/trade_group_pnl.py` — positions, live positions, quotes, live
executions, price magnifiers, security-master expiries, option metrics, and the
account-level newest `as_of_date`, in a fixed seven queries. It is one loader on
purpose: a magnifier fetched on one path and not another is how a cents-quoted
future comes out 100x wrong on one screen and right on the next.

**Cost-basis convention.** The two sources store `avg_cost` in **different units**,
and this is the single most error-prone thing in the overlay:

| Source                     | Column                    | Convention                                                                                |
| -------------------------- | ------------------------- | ----------------------------------------------------------------------------------------- |
| TWS `ib.positions()`       | `live_positions.avg_cost` | Per-unit cost **already including the multiplier** — the full dollar cost of one contract |
| FlexQuery `costBasisPrice` | `positions.avg_cost`      | Per-unit price, multiplier **not** applied                                                |

Every consumer — `compute_unrealized` here, and the frontend's Cost Basis column —
computes `qty·avg_cost` and reads dollars. None multiplies by `multiplier`. So the
settled value is normalized **up** at the read boundary via
`normalize_settled_avg_cost`, and the stored column keeps matching the raw IBKR
report. Without it a settled-backed option row reports cost basis 100x too small
and a futures row 1000x too small.

So: `cost_basis = qty·avg_cost`, `market_value = qty·mark·multiplier`, and
`unrealized = qty·mark·multiplier − qty·avg_cost`.

**Validating a change to this:** IBKR's own `fifo_pnl_unrealized` is the oracle.
`qty·mark·multiplier − qty·avg_cost` must equal it on every row; anything else
means the units are wrong somewhere.

### Consuming endpoints

Both are additive — existing settled fields are unchanged, and with no live data
the responses match prior behavior.

- `GET /trade-groups/{id}/executions` — merges live overlay for the group's
  `(account_id, con_id)` pairs. Adds per-position `source` / `mark` / `mark_ts` /
  `live_unrealized` and top-level `intraday_unrealized_pnl` /
  `intraday_realized_pnl` / `intraday_total_pnl` / `marks_as_of`.
- `GET /trade-groups?include_intraday=true` — the same overlay computed for
  **many groups at once**, behind the Strategy P&L table. Loads the union of
  every visible group's pairs once, then slices per group and reuses
  `overlay_totals()`, so the query count is fixed in the row count. The merge
  itself runs per group rather than once over the union: `merge_positions()`
  drops a settled row when _its account_ has live data, so a union-wide merge
  would net-close a group whose own pairs have no live rows. Defaults to `false`
  so the Strategies left panel and the group picker keep their two-query cost.
  Adds a group-level `live_is_stale`, true only when the group has
  overlay-backed rows and **every** one of them is stale — a mix of fresh and
  stale legs is not flagged, because `marks_as_of` already carries the age and
  flagging a whole row on one stale leg trains the operator to ignore the badge.
  It keys on whether a live row _exists_, not on the resulting `source`: a stale
  row now resolves to `settled`, so the old `source == "live"` filter reported a
  fully-stale group as fresh.
- `GET /positions` — portfolio-wide overlay with its own inline merge (not the
  `merge_positions()` helper); live qty/cost/mark preferred **while fresh**, and
  positions opened since the snapshot surfaced as additional rows. A live-only
  row whose account has a newer settled snapshot is a _closed_ position, not a
  new one, and is omitted — see **Overlay invalidation**. Also adds
  `live_is_stale`: true when the live snapshot predates a newer settled/Flex
  import from the same or a later day (`is_live_stale()` in
  `src/services/intraday_overlay.py`), so the UI can report that a capture exists
  and how old it is while the numbers come from the snapshot.

## UI

The Strategies page (`/strategies`), the Strategy P&L table (`/strategies/table`),
and the Positions page each show a **"Refresh Live (TWS)"**
button that enqueues `intraday.sync.tws` and re-fetches after the job runs. Live
mark / live-unrealized columns and intraday P&L totals render alongside the
settled values, with a freshness indicator: `live as of HH:MM` when a fresh
live mark is present, an amber `stale <when>` badge when `live_is_stale` is
true (overlay columns blanked), else `settled`.

The badge timestamp is **date-qualified whenever it is not from today**
(`formatMarkTime` in `frontend/src/lib/markTime.ts`). A bare time is fine for the
green live case, which is today by definition, and actively misleading for the
stale case — the overlay has no source to reconnect to over a weekend, so a
multi-day-old capture is routine, and `stale 11:09 PM` read as tonight.

Because a stale overlay now resolves to `source: settled`, such a row shows the
gray `settled` chip while the panel header still reports `stale as of <when>` —
the row says where its numbers came from, the header says why the live columns
are blank.

## Operational notes

- Requires a TWS/Gateway session reachable during market hours; `reqTickers` on
  all held conids consumes IBKR market-data lines (manual trigger keeps this
  bounded). FlexQuery sync remains session-free.
- Worker uses delayed-frozen market data (`reqMarketDataType(3)`) so it returns
  marks when live data isn't entitled.

## Preemptive tagging of unsettled fills

Today's TWS fills in `live_executions` can be assigned to a trade group **before
they settle**, keyed by `ib_exec_id` in `trade_group_live_executions`. The
Trades page surfaces unsettled fills (flagged `settled:false`, `data_source =
"tws-live"`) alongside settled executions and tags them per-fill via
`POST /trade-groups/{id}/live-executions:assign|unassign`.

A live combo is tagged as **one unit**, not once per fill. Legs carry their
summary's `parent_ib_exec_id` so the Trades table renders one combo owning a
single Tag Group cell, and assign/unassign fan out across the whole order via
`_live_combo_siblings`. That fan-out is load-bearing, not cosmetic: position
attribution is keyed by `con_id` and a BAG carries a placeholder conId matching
no position, so tagging the summary alone would attribute nothing.

On settlement, the shared carry-over (`src/services/group_link_carryover.py`)
folds the live link into the canonical `trade_group_executions` and drops it —
so grouping survives the live→settled handoff with no gap and no double-count.
It runs in **both** sync paths: the intraday purge and, robustly, at the end of
the FlexQuery trade sync (so a fill that settles overnight is reconciled even if
no intraday sync runs).

## Display parity with settled rows

Unsettled rows render with the same contract label and Action column as settled
FlexQuery rows. Two values the live feed doesn't hand over directly:

- **Expiry.** Ingest stores IBKR's `lastTradeDateOrContractMonth` raw on
  `live_executions.last_trade_date` (either `YYYYMMDD` or `YYYYMM`); the display
  layer normalizes both. When it's absent the label falls back to inferring the
  month from `local_symbol` — exact for OCC-style equity options, month-only for
  futures options, whose local symbol carries no day.
- **Action (Open/Close).** The real-time `ib_async.Execution` has no `openClose`
  or `positionEffect` — the settled indicator comes from FlexQuery's
  `Open/CloseIndicator`, a post-trade FIFO netting determination IBKR never
  stamps on a fill. So it is **derived**: `combo_summary` → "Roll", else non-zero
  `realized_pnl` → "Close" (IBKR reports realized P&L only on a
  position-reducing fill), else "Open". Best-effort by design — an exact
  breakeven scratch close reads as Open, and FlexQuery's authoritative indicator
  supersedes it at settlement.

**Expired is unreachable here.** An option expiration produces no fill, so it
never appears in the real-time feed; it books only via FlexQuery (see
`book_event` below). Unsettled rows never show Expired — a data-source limit,
not a bug.

## Orphan reconciliation

The exact-id purge only clears live rows whose `ib_exec_id` settled verbatim.
`src/services/live_reconcile.py` runs at the end of **both** sync paths — the
FlexQuery trade sync and the intraday sync, in the same transaction as
`_purge_settled` — and clears the rows that would otherwise linger as phantom
"unsettled" fills (and, for the first class, double-count realized P&L). Three
classes, in order:

| Class         | Divergence                                                                      | How it clears                                                                         |
| ------------- | ------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| `leg_strip`   | live combo leg carries an extra trailing segment (`…03.01.01`)                  | strip the last segment → exact settled id                                             |
| `book_event`  | expiry/assignment/exercise books as `FLEX-TX-…` with an `Ep`/`A`/`Ex` note      | match on account, conId, qty, side, price and trade date                              |
| `bag_summary` | live BAG summary has **no** settled counterpart — FlexQuery synthesizes its own | purge once no live _leg_ shares its order key and settled legs exist at its timestamp |

Running it on the intraday path too is load-bearing, not belt-and-braces: the
fills window is a rolling `FILLS_LOOKBACK_DAYS` lookback, so TWS keeps
re-reporting these fills for days. Their ids never equal the settled ones, so
`_purge_settled` can't see them and every intraday sync re-created the exact
rows a prior FlexQuery-side reconcile had just cleared.

`bag_summary` is a redundancy purge, not a match: the live BAG shares no id,
contract or order key with anything settled. "No live _legs_ left" is the
proof its legs settled (a leg only leaves `live_executions` by settling), and
the settled-legs check guards a summary that arrived with no legs at all. Its
group tag fans out onto those settled legs before the row is deleted, so
membership is never lost.

Peer BAG summaries are excluded from that count. A combo filling in several
partial executions emits one summary per partial, all sharing the order's
`permId`; counting those as siblings deadlocked them against each other and
left both as permanent phantom "unsettled" rows. A peer summary is never
evidence that a leg is still outstanding.

## Option metrics overlay (separate job)

Held option positions (OPT/FOP) also carry live greeks/IV and a derived
extrinsic/intrinsic split, fetched by a **separate** job (`option_metrics.sync.tws`)
that writes its own `latest_option_metrics` table and rides this overlay's
read-time merge. Kept separate so the two jobs never clobber each other's columns
and can run on independent cadences. See [option-metrics-overlay.md](option-metrics-overlay.md).

Both sides land in the same `merge_positions()` helper in `intraday_overlay.py`, so
the math is single-source; only the inputs differ. The API endpoint passes
`price_magnifier` and `latest_option_metrics`; `trade_group_pnl` calls it with those
arguments defaulted to `None`.

## Known limitations (deferred)

- No interval auto-refresh (manual buttons only); no historical intraday
  time-series (only the latest live state is stored).

## Reference

Original design and rationale: [../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md](../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md).
