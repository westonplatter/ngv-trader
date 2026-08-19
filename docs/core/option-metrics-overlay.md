---
topics: ["options", "greeks", "iv", "live-data", "risk-metrics", "tws"]
code_dirs_or_files:
  [
    "src/services/option_metrics_sync_tws.py",
    "src/services/intraday_overlay.py",
    "src/models.py",
  ]
description: Live option greeks and IV overlay — modelGreeks fetch, intrinsic/extrinsic split, and read-time merge on held positions.
---

# Option Metrics Overlay

Current-state doc for the live option greeks/IV overlay on **held** option
positions (OPT/FOP), layered on the intraday TWS overlay. It adds implied
volatility, delta/gamma/theta/vega, underlying price, and a derived
extrinsic/intrinsic split of the mark. Read [intraday-tws-overlay.md](intraday-tws-overlay.md)
first — this is a sibling job that shares that overlay's read-time merge.

## Purpose

The intraday overlay marks options with a price only. To judge and manage open
option structures intraday the operator also needs the live risk picture — IV,
the greeks, and how much of the mark is intrinsic vs time value. Those come from
the same `ib.positions()` tickers the overlay already touches (`ticker.modelGreeks`),
so no extra IBKR round-trips are required to surface them.

## Why a separate job

Greeks are fetched by a **separate** job (`option_metrics.sync.tws`), not folded
into the mark fetch (`intraday.sync.tws`). Both jobs upsert per `con_id`; if they
shared one table each would clobber the other's columns on write. Splitting them
gives each its own table and its own cadence — refresh marks frequently, greeks
less often, without coupling. The two never race.

## Data model

One additive table, written **only** by the metrics job. `latest_quote`,
`live_positions`, and `live_executions` are untouched.

| Table                   | Holds                                                     | Key                                |
| ----------------------- | --------------------------------------------------------- | ---------------------------------- |
| `latest_option_metrics` | live `iv`, `delta`, `gamma`, `theta`, `vega`, `und_price` | `con_id` (supplied, not generated) |

Sec-type-agnostic (OPT/FOP) and intentionally **not** FK'd to the futures-only
`contracts` table — mirrors `latest_quote`, and distinct from the research-path
`latest_futures_options` (FK'd, carries prices too).

## Sync flow

```text
"Refresh Metrics (TWS)" button ─► POST /positions/sync/option-metrics-tws
   ─► enqueue Job(option_metrics.sync.tws)
   ─► worker: handle_option_metrics_sync_tws → run_option_metrics_sync(engine, ib)
        ib.positions()                    → filter to OPT/FOP
        qualifyContracts + reqTickers     → ticker.modelGreeks
        upsert latest_option_metrics (con_id, newest-wins)
```

Service `src/services/option_metrics_sync_tws.py`; job `option_metrics.sync.tws`;
handler in `src/workers/jobs.py`. Self-contained — it calls `ib.positions()`
itself, so it never depends on the mark job having run first. Greek extraction
mirrors `market_data.py` and every field passes through `_safe_float`, so a
NaN/inf/IBKR-sentinel value never lands in a row.

## Read-time intrinsic/extrinsic split

Computed at read time in `intraday_overlay.option_value_split` (pure, no DB) from
the position's mark, right, strike, and the metric's underlying price:

- intrinsic (per unit): call → `max(0, und − strike)`; put → `max(0, strike − und)`
- extrinsic (per unit): `max(0, mark − intrinsic)`

Each part is `None` when its inputs are missing (non-option row, no underlying
price, or no mark). Values are per-unit prices in the **same unit as `mark`** —
the multiplier is applied only when converting to a dollar figure, per the
overlay's cost-basis convention. No P&L math changes.

## Read path / API

Greeks ride the existing overlay merge: `merge_positions` takes an optional
`metrics` map (`{con_id: LatestOptionMetrics}`) and populates the new
`PositionView` fields for option rows. Both consuming endpoints load
`latest_option_metrics` and expose the fields additively — all default null, so
non-option rows and no-live-data cases are unchanged:

- `GET /positions`
- `GET /trade-groups/{id}/executions`

Response fields: `iv`, `delta`, `gamma`, `theta`, `vega`, `und_price`,
`intrinsic_value`, `extrinsic_value`.

## UI

Positions page adds a **"Refresh Metrics (TWS)"** button and option-metric
columns, banded with the other live (TWS) columns:

- Always shown: **IV**, **Delta**, **Extrinsic**, **Intrinsic**.
- Behind a **"Show greeks"** toggle (default off): **Gamma**, **Theta**, **Vega**.
- Values render only for OPT/FOP rows; other sec types show "—".
- IV formats as a percentage; delta to 2 significant figures; gamma/theta/vega as
  signed decimals; extrinsic/intrinsic as prices.
- Privacy mode: IV and the greeks are risk metrics (not dollar exposure) and stay
  visible; extrinsic/intrinsic are per-unit prices and are masked like `mark`.
- Freshness reuses the overlay's existing `mark_ts` / "live as of HH:MM" indicator.

## Operational notes

- Zero extra IBKR round-trips beyond the metrics job's own `reqTickers`; greeks
  come off tickers, not a separate request.
- `reqMarketDataType(3)` (delayed-frozen) is set, so delayed greeks return when
  live entitlement is absent — acceptable for an overlay.
- The sync logs option-quote coverage (`with_greeks` vs total) and warns per
  option `con_id` that returns no `modelGreeks`, without failing the run.

## Scope

Held positions only — the job reads greeks off the tickers of instruments
returned by `ib.positions()`. **Pre-trade / quote-chain option analytics** (greeks
on prospective, not-yet-held contracts) are out of scope and belong to the
research/pricing path (`fetch_futures_options` → `latest_futures_options`, the
Pricing/Structures UI), not this positions overlay.

## Known limitations

- No historical intraday greek time-series for positions (only the latest state
  is stored); the research path owns `ts_futures_options` for that need.
- Greeks require a delayed/live market-data entitlement; illiquid strikes may
  return no `modelGreeks` — the row still shows its mark, metrics left null.
- Intrinsic/extrinsic assume the mark and strike/underlying share a price unit;
  price-magnified products (e.g. some grain FOPs) can skew — a known follow-up,
  same family as the deferred `latest_futures` underlying-price fallback.
