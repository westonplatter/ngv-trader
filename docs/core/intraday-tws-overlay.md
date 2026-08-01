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
- **Settle handoff:** a live fill whose `ib_exec_id` already exists in settled
  `trade_executions` is purged; the read-time merge also drops such duplicates.
  Tomorrow's FlexQuery sync ingests today's fills as settled — no double count.
  This is load-bearing, not just a dedup nicety: because the fills window reaches
  back past settlement, `_purge_settled` (write path, same transaction) and the
  read-path filter are what keep FlexQuery authoritative. See
  [the fills-window learning](../solutions/logic-errors/tws-fills-window-anchored-to-session-roll.md).
- **Combo roles:** the feed delivers a combo order as one `BAG` summary fill
  plus one fill per leg. Each fill stores its order key (`ib_perm_id`, falling
  back to `ib_order_id`) and `_exec_roles_by_exec_id` resolves `exec_role` over
  the whole batch — within an order group the BAG becomes `combo_summary` and
  its siblings `leg`. Mirrors FlexQuery's `_combo_groups` ≥2-distinct-conid
  guard, so a lone BAG or single-leg order stays `standalone`. Roles are
  recomputed per batch, keeping the upsert idempotent on `ib_exec_id`.

## Read-time merge

`src/services/intraday_overlay.py` holds pure, DB-free merge/PnL helpers:

- `merge_positions(flex_rows, live_rows, quotes)` — prefer live qty/cost/mark,
  fall back to the FlexQuery row; drop net-closed; surface opened-today rows.
- `intraday_unrealized_total`, `marks_as_of`, `dedupe_live_realized`.
- `compute_unrealized` / `parse_multiplier` — the shared cost-basis convention.

**Cost-basis convention (pending live validation).** IBKR `avgCost` from
`ib.positions()` is the per-unit cost **already including the contract
multiplier**. So `cost_basis = qty·avg_cost`, `market_value = qty·mark·multiplier`,
and `unrealized = qty·mark·multiplier − qty·avg_cost`. This is encoded once in
`intraday_overlay.py` with a `TODO(live-validation)` to confirm against known
FUT/STK/OPT positions vs the TWS UI during market hours.

### Consuming endpoints

Both are additive — existing settled fields are unchanged, and with no live data
the responses match prior behavior.

- `GET /trade-groups/{id}/executions` — merges live overlay for the group's
  `(account_id, con_id)` pairs. Adds per-position `source` / `mark` / `mark_ts` /
  `live_unrealized` and top-level `intraday_unrealized_pnl` /
  `intraday_realized_pnl` / `intraday_total_pnl` / `marks_as_of`.
- `GET /positions` — portfolio-wide overlay with its own inline merge (not the
  `merge_positions()` helper); live qty/cost/mark preferred, opened-today
  positions surfaced as additional rows. Unlike `merge_positions()`, it has no
  equivalent net-closed check, so a position that closed out intraday can
  still surface a stale settled-only row.

## UI

Both the Tagging page (`/tagging`) and the Positions page show a **"Refresh Live (TWS)"**
button that enqueues `intraday.sync.tws` and re-fetches after the job runs. Live
mark / live-unrealized columns and intraday P&L totals render alongside the
settled values, with a freshness indicator (`live as of HH:MM` when marks are
present, else `settled`).

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
`src/services/live_reconcile.py` runs after each FlexQuery sync and clears the
rows that would otherwise linger as phantom "unsettled" fills (and, for the
first class, double-count realized P&L). Three classes, in order:

| Class         | Divergence                                                                      | How it clears                                                                           |
| ------------- | ------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `leg_strip`   | live combo leg carries an extra trailing segment (`…03.01.01`)                  | strip the last segment → exact settled id                                               |
| `book_event`  | expiry/assignment/exercise books as `FLEX-TX-…` with an `Ep`/`A`/`Ex` note      | match on account, conId, qty, side, price and trade date                                |
| `bag_summary` | live BAG summary has **no** settled counterpart — FlexQuery synthesizes its own | purge once no live sibling shares its order key and settled legs exist at its timestamp |

`bag_summary` is a redundancy purge, not a match: the live BAG shares no id,
contract or order key with anything settled. "No live siblings left" is the
proof its legs settled (a leg only leaves `live_executions` by settling), and
the settled-legs check guards a summary that arrived with no legs at all. Its
group tag fans out onto those settled legs before the row is deleted, so
membership is never lost.

## Option metrics overlay (separate job)

Held option positions (OPT/FOP) also carry live greeks/IV and a derived
extrinsic/intrinsic split, fetched by a **separate** job (`option_metrics.sync.tws`)
that writes its own `latest_option_metrics` table and rides this overlay's
read-time merge. Kept separate so the two jobs never clobber each other's columns
and can run on independent cadences. See [option-metrics-overlay.md](option-metrics-overlay.md).

## Known limitations (deferred)

- No interval auto-refresh (manual buttons only); no historical intraday
  time-series (only the latest live state is stored).

## Reference

Original design and rationale: [../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md](../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md).
