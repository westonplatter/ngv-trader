# Spec: Real-time Option Metrics Overlay

> **Status: PROPOSED — not implemented (as of 2026-07-08).** Extend the existing
> intraday TWS overlay so option positions carry live IV, delta (and the other
> greeks), plus derived extrinsic/intrinsic value, alongside the live mark.

## Complexity: 2

Additive extension of an already-shipped feature. One Alembic migration (widen
`latest_quote`), reuse of the existing `modelGreeks` extraction from
`market_data.py`, small read-time compute for intrinsic/extrinsic, and additive
response + UI columns. No new tables, jobs, or IB round-trips.

## Purpose

The intraday TWS overlay already layers live current-state quantity, cost, mark,
and unrealized P&L on top of the settled FlexQuery snapshot. For option
positions the operator also needs the live risk picture — implied volatility,
delta (and the rest of the greeks), and the extrinsic/intrinsic split of the
mark — to judge and manage open structures intraday. These are currently only
computed for the futures-options *research* tables, never for held positions.

## Problem

- The overlay marks options with a price only. `docs/core/intraday-tws-overlay.md`
  lists this explicitly under Known limitations: *"No greeks/IV on the live mark
  (mark price only)."*
- To see live IV/delta for a held option the operator must leave the app and
  read TWS directly; there is no extrinsic/intrinsic decomposition anywhere for
  positions.
- The data is already on the wire: the same `reqTickers` call the overlay makes
  returns `ticker.modelGreeks` (impliedVol, delta, gamma, theta, vega, undPrice)
  for options — it is simply dropped in `_write_quotes`.

## Scope

- Capture greeks (IV, delta, gamma, theta, vega, underlying price) for held
  option positions during the existing intraday sync, from the tickers already
  fetched — no additional IB requests.
- Persist them on the unified live table (`latest_quote`) keyed by `con_id`.
- Compute per-unit intrinsic and extrinsic value at read time from the live mark,
  strike, right, and underlying price.
- Surface IV / delta / extrinsic / intrinsic (and the remaining greeks) on the
  `GET /positions` and `GET /trade-groups/{id}/executions` responses and render
  them in the Positions and Tagging tables for option rows.
- Keep everything additive: non-option rows and no-live-data cases are unchanged.

## Non-goals

- Streaming tick subscriptions (`reqMktData` callbacks). The overlay stays a
  snapshot pull per sync; "real-time" here means "as of the latest live sync."
- A historical intraday greek time-series for positions (no per-position `ts_*`
  table). The research path already owns `ts_futures_options` for that need.
- Interval auto-refresh is optional and split into a later phase (see Rollout);
  Phase 1 keeps the manual "Refresh Live (TWS)" trigger.
- Position-level aggregate greeks (portfolio delta/vega roll-ups). Per-position
  greeks are provided; roll-ups can follow once the per-row data exists.
- Recomputing IB's model greeks locally; we store what TWS returns.
- **Pre-trade / quote metrics.** Metrics are shown for *held* option positions
  only — the overlay reads greeks off the tickers of instruments returned by
  `ib.positions()`. Pre-trade option analytics (greeks on prospective, not-yet-
  held contracts, e.g. shopping a futures-options chain before entry) are a
  separately-wanted capability and explicitly out of scope here; they belong to
  the research/pricing path (`fetch_futures_options`, `latest_futures_options`,
  the Pricing/Structures UI), not this positions overlay.

## Current State

- `src/services/intraday_sync_tws.py::run_intraday_sync` does one IB session:
  `ib.positions()` → `live_positions`; `qualifyContracts` + `reqTickers(held)` →
  `latest_quote` via `_write_quotes`; `ib.fills()` → `live_executions`.
- `_write_quotes` reads only bid/ask/last/close and the selected `mark`; it does
  **not** touch `ticker.modelGreeks`.
- `LatestQuote` (`src/models.py`) is sec-type-agnostic, keyed by `con_id`, and
  holds bid/ask/last/close/mark/market_ts only.
- The greek-extraction pattern already exists in
  `src/services/market_data.py` (`fetch_futures_options`, `fetch_snapshot`):
  `greeks = ticker.modelGreeks; iv = greeks.impliedVol; delta = greeks.delta; …;
  und_price = greeks.undPrice`, with a `latest_futures` fallback for und_price.
  It writes the futures-only `latest_futures_options` / `ts_futures_options`
  tables (FK'd to `contracts`), which are not used by the position overlay.
- Read-time merge lives in `src/services/intraday_overlay.py` (`merge_positions`
  → `PositionView`); the `/positions` router builds `PositionResponse` inline and
  the trade-group executions endpoint reuses the same helpers.
- Frontend `PositionsTable.tsx` renders the overlay columns (Live Mark, Live
  Unrealized, Freshness) driven off `source == "live"`.

## Desired Outcome

- After a live sync during market hours, each held option row shows live IV,
  delta, gamma, theta, vega, underlying price, and an intrinsic/extrinsic split
  of the mark.
- Non-option rows (FUT/STK) show blanks for those columns — no regressions.
- With no TWS session the fields are null and the tables degrade to the settled
  view exactly as today.

## UX Requirements

- Positions and Tagging tables gain option-metric columns: **IV**, **Delta**,
  **Extrinsic**, **Intrinsic** (primary), with **Gamma/Theta/Vega** available.
  Given table width, group the greeks behind a "Show greeks" toggle (default:
  IV + Delta + Extrinsic + Intrinsic visible, secondary greeks collapsed).
- Values render only for OPT/FOP rows; other sec types show "—".
- IV formats as a percentage (e.g. `24.5%`); delta/gamma/theta/vega as signed
  decimals; extrinsic/intrinsic as prices via the existing money formatter.
- Greek columns respect privacy mode consistently with existing price columns
  (IV/delta are risk metrics, not dollar exposure — show them; extrinsic and
  intrinsic are per-unit prices — mask like `mark`).
- Freshness of greeks is the existing `mark_ts` / "live as of HH:MM" indicator;
  no separate stamp.

## Functional Plan

1. Widen the live quote table to carry greeks.
   - Alembic migration adds nullable `iv`, `delta`, `gamma`, `theta`, `vega`,
     `und_price` to `latest_quote` (mirrors `latest_futures_options`).
   - Nullable so FUT/STK quotes leave them null; no backfill needed.
2. Populate greeks during the intraday sync.
   - In `_write_quotes`, read `ticker.modelGreeks` exactly as `market_data.py`
     does and include the six fields in the upsert values.
   - Underlying-price fallback: when `modelGreeks.undPrice` is missing, leave
     `und_price` null (the position overlay has no per-symbol future prefetch
     like the research path; a fallback join is a follow-up, not Phase 1).
   - Guard every field through the existing `_safe_float` (rejects NaN/inf and
     the IBKR sentinel) so a missing greek never poisons a row.
3. Compute intrinsic/extrinsic at read time (pure, in `intraday_overlay.py`).
   - New helper `option_value_split(mark, right, strike, und_price) ->
     (intrinsic, extrinsic)`:
     - intrinsic per unit: call → `max(0, und_price − strike)`; put →
       `max(0, strike − und_price)`; `None` if any input missing or the row is
       not an option.
     - extrinsic per unit: `mark − intrinsic` (clamped at 0); `None` when mark or
       intrinsic is unavailable.
   - These are per-unit prices in the same unit as `mark` (multiplier applied
     only for dollar value, consistent with the documented cost-basis
     convention). No P&L math changes.
4. Thread the fields through the read paths.
   - Extend `PositionView` with `iv`, `delta`, `gamma`, `theta`, `vega`,
     `und_price`, `intrinsic_value`, `extrinsic_value`; populate in
     `merge_positions` from the quote + computed split (option rows only).
   - Extend `PositionResponse` (positions router) and the trade-group executions
     item model with the same optional fields; populate inline where the router
     already reads the quote.
5. Render in the UI.
   - Add the columns to `PositionsTable.tsx` (and the Tagging table if it renders
     its own position rows) with the "Show greeks" toggle and formatting above.
   - Extend the `Position` TS interface and the demo fixtures / `demoApi.ts` so
     the screenshot path shows populated option metrics.

## Data Model and State Changes

- `latest_quote`: add nullable `iv`, `delta`, `gamma`, `theta`, `vega`,
  `und_price` (Float). Single additive Alembic migration; downgrade drops them.
- No change to `live_positions` or `live_executions`.
- Response additions (all optional, default null): `PositionResponse` and the
  trade-group executions item gain `iv`, `delta`, `gamma`, `theta`, `vega`,
  `und_price`, `intrinsic_value`, `extrinsic_value`.
- SSE: unchanged — the existing `positions` coarse event already drives a
  re-fetch of the enriched snapshot.

## API / Worker / Service Changes

- `intraday_sync_tws._write_quotes`: read `modelGreeks`, upsert six new columns.
- `intraday_overlay`: add `option_value_split` and the new `PositionView` fields;
  no signature change to `merge_positions` inputs (greeks ride on the existing
  quote objects).
- `positions` router and trade-group executions endpoint: populate the new
  response fields from the quote/computed split.
- No new job type, no scheduler change in Phase 1 (piggybacks on
  `intraday.sync.tws`).

## Operational Considerations

- Zero additional IB round-trips: greeks come from the tickers already fetched by
  the existing `reqTickers` batch. Market-data line usage is unchanged.
- `reqMarketDataType(3)` (delayed-frozen) already set; delayed greeks are
  returned when live entitlement is absent — acceptable for an overlay.
- Idempotent: the `latest_quote` upsert (`on_conflict_do_update` on `con_id`)
  simply carries the extra columns; re-runs overwrite newest-wins as today.
- Log when an option ticker returns no `modelGreeks` (reuse the existing
  `market_data` warning shape) so gaps are visible without failing the sync.

## Risks

- **Missing greeks for some options.** Not every FOP/OPT returns `modelGreeks`
  from a snapshot (illiquid strikes, no entitlement). Mitigation: nullable
  fields, null-safe formatting, per-row warning log; the row still shows mark.
- **Underlying price gaps** make intrinsic/extrinsic null. Accepted for Phase 1;
  a `latest_futures`/underlying join fallback is a follow-up.
- **Unit/multiplier confusion** for extrinsic/intrinsic vs mark. Mitigation:
  keep them per-unit prices in the same unit as `mark`; do not fold multiplier
  in; reuse the single documented convention.
- **Table width / readability.** Mitigation: the "Show greeks" toggle keeps the
  default view compact.

## Observability

- Reuse the existing `run_intraday_sync` completion log; add a count of option
  quotes that carried greeks vs total option quotes.
- Warn (not error) on option tickers with no `modelGreeks`.
- No new metrics required; freshness surfaces via the existing `marks_as_of`.

## Rollout

1. Migration + `_write_quotes` greek capture (backend only; columns populate on
   the next live sync).
2. `option_value_split` + `PositionView`/response fields; verify `/positions`
   and executions responses carry the new fields.
3. UI columns + "Show greeks" toggle + demo fixtures; capture the demo
   screenshot per the UI-change convention.
4. Update `docs/core/intraday-tws-overlay.md` (remove the greeks/IV item from
   Known limitations, document the new columns) and fold this spec into it; keep
   the interval-auto-refresh item.
5. (Optional, later phase) Interval auto-refresh so the overlay updates without a
   button press, and an underlying-price fallback for intrinsic/extrinsic.

## Acceptance Criteria

- After a live sync with a TWS session, an open option position shows non-null
  IV and delta and an intrinsic + extrinsic that sum (± rounding) to the live
  mark, in both `/positions` and the Tagging view.
- A FUT or STK position shows null/"—" for all option-metric columns and is
  otherwise unchanged.
- With no live data, responses match today's settled-only shape (new fields
  null) and no UI regression occurs.
- The intraday sync issues no additional IB requests beyond today's baseline.
- `uv run python scripts/check.py`, Pyright, and `scripts/doc_check.py` pass; the
  demo screenshot renders populated option metrics.

## Open Questions

- Which greeks are "primary" vs behind the toggle? Proposed default: IV, Delta,
  Extrinsic, Intrinsic visible; Gamma/Theta/Vega collapsed.
- Should Phase 1 include the `latest_futures` underlying-price fallback for
  intrinsic/extrinsic, or defer it? Proposed: defer.
- Is interval auto-refresh wanted now or later? Proposed: later phase.

## Related Files

- `src/services/intraday_sync_tws.py` (`_write_quotes`, `run_intraday_sync`)
- `src/services/intraday_overlay.py` (`merge_positions`, new `option_value_split`)
- `src/services/market_data.py` (existing `modelGreeks` extraction to mirror)
- `src/models.py` (`LatestQuote`) + a new `alembic/versions/*` migration
- `src/api/routers/positions.py`, `src/api/routers/trade_groups.py`
- `frontend/src/components/PositionsTable.tsx`, `frontend/src/components/TradeTaggingPage.tsx`
- `frontend/src/lib/demoData.ts`, `frontend/src/lib/demoApi.ts`
- `docs/core/intraday-tws-overlay.md` (current-state doc to update on ship)
</content>
</invoke>
