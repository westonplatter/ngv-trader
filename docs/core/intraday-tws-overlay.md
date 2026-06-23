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
fall out without lot arithmetic. Fills drive *realized* attribution only, never
quantity.

## Data model (separate from FlexQuery)

Three additive tables hold the overlay; the FlexQuery `positions` /
`trade_executions` tables are never touched.

| Table | Holds | Key |
| --- | --- | --- |
| `live_positions` | current TWS qty + blended `avg_cost` per holding | unique `(account_id, con_id)` |
| `latest_quote` | live marks (bid/ask/last/close + selected `mark`) for any sec type | `con_id` (supplied, not generated) |
| `live_executions` | today's fills with `realized_pnl` | unique `ib_exec_id` (dedup vs settled) |

`latest_quote` is sec-type-agnostic (FUT/FOP/STK/OPT) and intentionally **not**
FK'd to the futures-only `contracts` table — distinct from `latest_futures*`
(which the term-structure feature continues to own; see [security-data.md](../security-data.md)).

## Sync flow

One manual-triggered job does all three fetches in a single IB session.

```
"Refresh Live (TWS)" button ─► POST /positions/sync/intraday-tws
   ─► enqueue Job(intraday.sync.tws)
   ─► worker: handle_intraday_sync_tws → run_intraday_sync(engine, ib)
        ib.positions()          → live_positions  (replace per account scope)
        qualifyContracts + reqTickers(held) → latest_quote (mark rule)
        ib.fills() (today, ET)  → live_executions, purge settled by ib_exec_id
```

Service: `src/services/intraday_sync_tws.py` (`run_intraday_sync`). Job type
`intraday.sync.tws`; handler in `src/workers/jobs.py`; see [workers.md](../workers.md).

Key rules (defined once in the service):

- **Mark selection:** `last` if present; else midpoint `(bid+ask)/2` when both
  sides exist; else `close`; else null (degrades to the snapshot mark).
- **Day boundary:** "today's fills" = at/after US-Eastern (exchange) midnight of
  the current session date, regardless of server timezone.
- **Exchange qualification:** `ib.positions()` returns contracts without an
  exchange, which `reqTickers` rejects. Held contracts are run through
  `qualifyContracts` first (real exchange for futures/index options; SMART
  fallback for equity-style) before requesting marks.
- **Replace semantics:** `live_positions` rows for the fetched accounts are
  cleared and re-inserted each run, so net-closed positions disappear.
- **Settle handoff:** a live fill whose `ib_exec_id` already exists in settled
  `trade_executions` is purged; the read-time merge also drops such duplicates.
  Tomorrow's FlexQuery sync ingests today's fills as settled — no double count.

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
- `GET /positions` — portfolio-wide overlay reusing the same helper; live qty/
  cost/mark preferred, opened-today positions surfaced as additional rows.

## UI

Both the TradeGroup view and the Positions page show a **"Refresh Live (TWS)"**
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

## Known limitations (deferred)

- A brand-new instrument opened today maps to no TradeGroup until tagged
  post-settle (it does appear on the portfolio Positions page).
- No greeks/IV on the live mark (mark price only).
- No interval auto-refresh (manual button only); no historical intraday
  time-series (only the latest live state is stored).

## Reference

Original design and rationale: [../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md](../plans/2026-06-09-001-feat-intraday-tws-overlay-plan.md).
