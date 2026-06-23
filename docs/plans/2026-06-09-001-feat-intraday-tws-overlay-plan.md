---
title: "feat: Intraday TWS overlay for live current-state P&L on FlexQuery positions"
type: feat
status: shipped
created: 2026-06-09
shipped: 2026-06-21
---

# feat: Intraday TWS overlay for live current-state P&L on FlexQuery positions

> **Status: SHIPPED (2026-06-21).** This document is retained as the original
> design and rationale. For how the feature works today, see the current-state
> doc: [docs/core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md).
> Differences from this plan as built: the read-time merge and frontend pieces
> (U4/U6) had no concurrent-agent collision; automated tests were omitted in
> favor of the repo's `ruff` + `scripts/check.py` validation; held contracts are
> run through `qualifyContracts` before `reqTickers` to supply the exchange.

## Summary

FlexQuery is the canonical settled record but lands T-1 (one business day old): the `positions` table holds yesterday's EOD quantities, marks, and `fifo_pnl_unrealized`, and the TradeGroup view sums those stale values. This feature adds a **live current-state overlay sourced from TWS**, surfaced on demand, **without touching the FlexQuery data**.

The core insight from scoping: a read-time overlay of live *marks* onto the stale snapshot is insufficient, because the snapshot's quantities are wrong intraday (positions opened today are missing, added/reduced positions show yesterday's size). The authoritative current state is `ib.positions()` from TWS — it already returns current quantity and TWS-blended average cost for every held contract, including ones opened today. So the overlay sources **current positions** (not just marks) from TWS into a **separate `live_positions` table**, fetches **live marks** into a unified `con_id`-keyed `latest_quote` table, and pulls **today's fills** into `live_executions` for intraday realized P&L. A read-time merge prefers live state, falling back to the FlexQuery snapshot where no live data exists.

A single manual-triggered TWS job does all three fetches in one session. The FlexQuery `positions` / `trade_executions` tables are never written by this feature.

**Target repo:** ngv-trader (this repo). All paths repo-relative.

**Coordination note:** Another agent is concurrently editing this codebase on a separate change set. This plan adds mostly *new* files (models additions, a new service, a new worker handler, a new router/route, new frontend display). The two read-time edits that touch shared code — `src/api/routers/trade_groups.py` (the executions endpoint) and the TradeGroup frontend component — are the only collision surfaces; sequence those units last and rebase on the other agent's work before editing.

---

## Problem Frame

- FlexQuery position + trade data settles T-1. Intraday, the trader cannot see true current exposure or live P&L.
- The TradeGroup strategy view (`/trade-groups/{id}/executions`) computes Unrealized P&L as `SUM(Position.fifo_pnl_unrealized)` over snapshot rows matched by `(account_id, con_id)` — entirely stale intraday.
- The four intraday mutations the overlay must represent correctly:
  1. **Opened today** — no FlexQuery snapshot row exists yet.
  2. **Added to** — current qty > snapshot qty; blended cost differs from snapshot avg cost.
  3. **Reduced** — current qty < snapshot qty; a slice realized today.
  4. **Net closed / flipped** — snapshot had a position; now flat or reversed.
- Constraint: do **not** delete or overwrite FlexQuery data — enhance it. FlexQuery stays the settled source of truth; TWS provides the live current-state layer.
- Accepted trade-off: this requires a TWS/Gateway session reachable during market hours (the FlexQuery switch had removed that requirement; live data inherently reintroduces it).

## Scope

In scope:
- New `live_positions` table: current TWS position state (qty, blended avg cost) per `(account_id, con_id)`, separate from FlexQuery `positions`.
- New unified `latest_quote` table: live marks (bid/ask/last/close + chosen mark) keyed by `con_id`, covering all sec types (FUT/FOP/STK/OPT).
- New `live_executions` table: today's TWS fills (with `ib_exec_id` for dedup against settled FlexQuery executions).
- New intraday TWS sync service: one job fetches `ib.positions()`, `reqTickers` on held conids, and today's fills; writes the three tables.
- New job type, worker handler, API route, and frontend "refresh live" button (manual trigger).
- Read-time reconciliation in the TradeGroup executions endpoint: merge live current-state + marks + intraday fills with FlexQuery fallback; compute intraday unrealized / realized / total with freshness metadata.
- Frontend display of intraday P&L alongside the settled snapshot, with an "as of" freshness indicator.

Out of scope:

### Deferred to Follow-Up Work
- Background/interval auto-refresh of live quotes (v1 is manual-button only).
- Portfolio-wide intraday overlay on the main Positions page (this plan targets the TradeGroup view; a thin follow-up reuses the same merge helper — see U5, marked optional).
- Auto-association of brand-new (opened-today) instruments to a TradeGroup before they are tagged post-settle.
- Greeks / IV on the live mark for options (mark price only in v1).
- Historical intraday P&L time-series (only "latest live" is stored; no `ts_*` archive for the overlay).

### Outside this change's identity
- Replacing FlexQuery with TWS as the primary sync path. FlexQuery remains canonical; TWS is an additive live layer.
- Order submission or any trading action.

---

## Key Technical Decisions

- **Current state comes from `ib.positions()`, not snapshot+delta reconstruction.** TWS returns authoritative current quantity and blended average cost per contract. This makes all four mutation cases (open / add / reduce / net-close) fall out for free — no manual lot arithmetic. Snapshot+fills only drive *realized* attribution, never current quantity.
- **Live state lives in separate tables; FlexQuery tables are untouched.** New `live_positions`, `latest_quote`, `live_executions`. The FlexQuery `positions` / `trade_executions` / their unique `(account_id, con_id)` constraint are never modified. This directly honors "enhance, don't delete" and avoids the constraint collision a shared table would create.
- **Read-time merge with FlexQuery fallback.** The endpoint composes the view at read time: prefer `live_positions` ⟕ `latest_quote`; fall back to FlexQuery `positions` row when no live row exists. No precomputed/denormalized P&L. Freshness is explicit per row (`live` vs `settled`, plus a timestamp).
- **Unified `latest_quote` keyed by `con_id` for all sec types.** Rather than extend the futures-only `latest_futures` / `latest_futures_options`, the overlay uses one `con_id`-keyed table covering FUT/FOP/STK/OPT. The existing futures tables remain for the term-structure feature; the overlay does not depend on them.
- **Intraday realized from today's TWS fills, deduped by `ib_exec_id`.** `live_executions` holds today's fills. At read time, any live fill whose `ib_exec_id` already exists in settled `trade_executions` is dropped (settled wins). The next intraday sync purges live fills that have since settled. This makes the T→T+1 settle handoff idempotent and double-count-free.
- **Mark selection rule:** `last` if present; else midpoint `(bid+ask)/2` when both sides exist; else `close`. A row with no usable price keeps a null mark and degrades to the FlexQuery snapshot mark. Documented once in the service and reused.
- **One TWS session, one job.** A single `intraday.sync.tws` job opens one IB session and performs positions + tickers + fills, minimizing connection churn and market-data subscription load. Manual button enqueues it, mirroring the existing kickoff-sync button pattern.
- **TradeGroup membership for live data reuses the existing `(account_id, con_id)` heuristic.** Live positions and live fills associate to a group by matching the `(account_id, con_id)` pairs already present in the group's settled executions — identical to how the current endpoint finds open positions. Known limitation (deferred): a brand-new instrument opened today maps to no group until tagged post-settle.

---

## High-Level Technical Design

*This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
                      ┌──────────────────────────── manual "refresh live" button
                      ▼
        enqueue Job(intraday.sync.tws)
                      ▼
   ┌──────────────────────────────────────────────┐
   │ intraday_sync_tws.run()  (one IB session)     │
   │   ib.positions()  ─► live_positions  (upsert) │
   │   reqTickers(held conids) ─► latest_quote     │
   │   today's fills   ─► live_executions (dedup)  │
   └──────────────────────────────────────────────┘

   FlexQuery (untouched):  positions(T-1) , trade_executions(settled)

   READ  /trade-groups/{id}/executions
     current_positions = live_positions ⟕ latest_quote
                         ⟕ fallback FlexQuery positions
     realized = settled_executions ∪ (live_executions − settled by ib_exec_id)
     per position:
        qty, avg_cost   ← live (or flex)
        mark, mark_ts   ← latest_quote (or flex mark_price/as_of_date)
        unrealized      ← (mark·qty·mult) − cost_basis(qty, avg_cost)
     totals: unrealized Σ, realized Σ, total = Σ+Σ
     freshness: per-row source flag + newest mark_ts
```

Reconciliation truth table (per `(account, con_id)`):

| Snapshot row | Live `ib.positions()` row | Result shown |
|---|---|---|
| present | present | live qty/cost/mark; unrealized on live qty |
| absent | present (opened today) | live qty/cost/mark; flex contributes nothing |
| present | absent (net closed) | dropped from open positions; realized via today's fills |
| present | present, opposite sign (flipped) | live signed qty/cost/mark |

---

## Output Structure

```
src/services/
  intraday_sync_tws.py        # NEW — ib.positions() + reqTickers + fills → 3 tables
  intraday_overlay.py         # NEW — read-time merge/PnL helper (shared, pure)
src/workers/
  jobs.py                     # MOD — handle_intraday_sync_tws + dispatcher entry
src/services/
  jobs.py                     # MOD — JOB_TYPE_INTRADAY_SYNC_TWS constant
src/models.py                 # MOD — LivePosition, LatestQuote, LiveExecution
src/api/routers/
  positions.py                # MOD — POST /positions/sync/intraday-tws (trigger)
  trade_groups.py             # MOD — overlay merge in executions endpoint
alembic/versions/
  <ts>_add_intraday_overlay_tables.py   # NEW
frontend/src/components/
  TradeTaggingPage.tsx        # MOD — refresh button + intraday P&L + freshness
```

---

## Existing Patterns to Follow

- Market-data fetch shape: `src/services/market_data.py` `fetch_snapshot()` already takes arbitrary `con_ids`, opens an IB session via the pool, calls `ib.reqTickers`, and upserts a latest table — mirror this for `latest_quote`.
- Dormant TWS position fetch: `src/services/position_sync_tws.py` `sync_positions_with_ib()` already calls `ib.positions()` and reads `position.position` / `position.avgCost` / contract metadata — reuse the fetch/parse shape, but write `live_positions` (not `positions`).
- Worker handler shape: `handle_market_data_snapshot` (`src/workers/jobs.py:524`) — signature `(job, engine, ib_pool) -> dict`, lazy service import inside the handler, registered in the `handlers` dict (`src/workers/jobs.py:635`).
- Job-type constants block: `src/services/jobs.py:17` (`domain.action.source` convention) — add `JOB_TYPE_INTRADAY_SYNC_TWS = "intraday.sync.tws"`.
- Manual kickoff button + route: `frontend/src/components/PositionsTable.tsx` `kickOffPositionSync` POSTing to a `/positions/sync/...` route that calls `enqueue_job(...)` + `db.commit()`.
- Realized P&L extraction: `_execution_realized_pnl(raw)` in `src/api/routers/trades.py:240` (handles both `commissionReport.realizedPNL` TWS shape and top-level `fifoPnlRealized` Flex shape) — reuse for live fills.
- TradeGroup open-position discovery: `src/api/routers/trade_groups.py` executions endpoint (~line 667+) builds `account_con_pairs` from group executions and joins `Position` — extend, do not rewrite.
- Migrations: generate via `alembic revision` then edit (never hand-author the revision id); closest precedent is any recent additive-table migration under `alembic/versions/`.

---

## Implementation Units

### U1. Add `live_positions`, `latest_quote`, `live_executions` models + migration

**Goal:** Persist the live overlay in tables fully separate from FlexQuery data.

**Requirements:** Supports cases open/add/reduce/net-close (current qty source), live marks (all sec types), intraday realized (fills with dedup key).

**Files:**
- `src/models.py`
- `alembic/versions/<ts>_add_intraday_overlay_tables.py` (generated, then edited)

**Approach:**
- `LivePosition`: `account_id` (FK), `con_id`, contract metadata (`symbol`, `sec_type`, `local_symbol`, `multiplier`, `right`, `strike`), `position` (Float, signed qty), `avg_cost` (Float, TWS-blended), `fetched_at` (DateTime). Unique `(account_id, con_id)`. No mark stored here — marks live in `latest_quote` and join at read time (keeps positions vs quotes separated).
- `LatestQuote`: `con_id` (PK), `bid`, `ask`, `last`, `close` (Float nullable), `mark` (Float nullable, the selected price), `market_ts` (DateTime, tick time), `ingested_at` (DateTime). Sec-type-agnostic.
- `LiveExecution`: `id` PK, `ib_exec_id` (Text, unique — dedup key matching `TradeExecution.ib_exec_id`), `account_id`, `con_id`, contract metadata, `side`, `quantity`, `price`, `realized_pnl` (Float nullable), `exec_time` (DateTime), `fetched_at`. Index `(account_id, con_id)`.
- Generate the migration with `alembic revision --autogenerate`, then hand-edit to confirm column types/constraints. `downgrade()` drops the three tables.

**Patterns to follow:** Existing `Position` (`src/models.py:126`) and `LatestFutures` (`src/models.py:562`) table definitions.

**Test scenarios:**
- After `alembic upgrade head`, the three tables exist with expected columns/constraints; `alembic downgrade -1` removes them cleanly (round-trip leaves schema identical).
- Inserting two `LivePosition` rows with the same `(account_id, con_id)` violates the unique constraint; differing con_ids succeed.
- Inserting two `LiveExecution` rows with the same `ib_exec_id` violates uniqueness.
- `LatestQuote` accepts a row with all price fields null except `close` (illiquid-option case).

**Verification:** `uv run python scripts/check.py src.models` passes; migration applies against a prod-DB snapshot in a `BEGIN; … ROLLBACK;` dry-run.

---

### U2. Intraday TWS sync service (`intraday_sync_tws.py`)

**Goal:** One service, one IB session: fetch current positions, live marks, and today's fills; write the three tables.

**Requirements:** Current qty/blended cost from `ib.positions()`; marks for all held conids; today's fills with `ib_exec_id`.

**Dependencies:** U1.

**Files:**
- `src/services/intraday_sync_tws.py`
- `tests/services/test_intraday_sync_tws.py`

**Approach:**
- `run_intraday_sync(engine, ib) -> dict` (session provided by the worker pool, matching `market_data.fetch_snapshot`):
  1. `ib.positions()` → upsert `live_positions` per `(account_id, con_id)`; **delete** live rows no longer returned (net-closed positions disappear). Account upsert via `src/services/sync_common.get_or_create_accounts`.
  2. Collect held `con_id`s; `ib.reqTickers(*contracts)` in batches (reuse `market_data` batching); apply the mark-selection rule (`last` → midpoint → `close`); upsert `latest_quote`.
  3. Today's fills via `ib.fills()` (or `reqExecutions` filtered to today); map each to `LiveExecution`, upsert by `ib_exec_id`. Purge `live_executions` whose `ib_exec_id` now exists in settled `trade_executions`.
- Return counts `{positions, quotes, fills, purged}`.
- Mark-selection rule and the "today" boundary (session date in account TZ) defined once here with a module constant/helper.
- **Implementation-time verification (deferred):** IBKR `avgCost` multiplier semantics differ by sec type (per-share vs per-contract incl. multiplier). Validate the cost-basis formula against one known futures, one equity, and one option position versus the TWS UI before wiring P&L. Record the resolved convention in `intraday_overlay.py` (U4).

**Execution note:** Start with a failing unit test that feeds a faked `ib` (stub `positions()`/`reqTickers()`/`fills()`) and asserts the three tables' resulting rows — the broker round-trip must be mockable.

**Patterns to follow:** `src/services/market_data.py` `fetch_snapshot` (session + reqTickers + upsert); `src/services/position_sync_tws.py` `sync_positions_with_ib` (positions parse); `src/services/sync_common.py` helpers.

**Test scenarios:**
- Happy path: stub returns 3 positions + tickers + 2 fills → `live_positions` has 3 rows, `latest_quote` 3 rows, `live_executions` 2 rows.
- Net-close: a `con_id` present in a prior `live_positions` row is absent from `ib.positions()` → its live row is deleted.
- Mark selection: ticker with `last=None, bid=1.0, ask=1.2` → stored `mark == 1.1`; with only `close` → `mark == close`; with no prices → `mark is None`.
- Dedup/purge: a `live_execution` whose `ib_exec_id` exists in `trade_executions` is purged on next run.
- Open-today: a position/fill for a `con_id` absent from FlexQuery `positions` still writes live rows (no dependency on a snapshot row).
- Multiplier sanity: a known equity-option fill produces `realized_pnl`/cost consistent with the documented convention (guards the avgCost gotcha).

**Verification:** Run against a live TWS session during market hours; the three tables populate; counts match the IB account.

---

### U3. Job type, worker handler, and manual-trigger API route

**Goal:** Enqueue and run the intraday sync from a button.

**Dependencies:** U2.

**Files:**
- `src/services/jobs.py`
- `src/workers/jobs.py`
- `src/api/routers/positions.py`
- `tests/api/test_positions_intraday_route.py`

**Approach:**
- Add `JOB_TYPE_INTRADAY_SYNC_TWS = "intraday.sync.tws"` to the constants block.
- Add `handle_intraday_sync_tws(job, engine, ib_pool) -> dict` to `src/workers/jobs.py`: lazy-import `run_intraday_sync`, acquire an IB session from the pool, call it, return counts. Register it in the `handlers` dict.
- Add `POST /positions/sync/intraday-tws`: enqueue the job + `db.commit()`, return 202 + `job_id`. Request body optional (`account_code?`). Mirror existing flex-sync route handlers.

**Patterns to follow:** `handle_market_data_snapshot` (`src/workers/jobs.py:524`) + its dispatcher entry (`:637`); existing `/positions/sync/...` routes.

**Test scenarios:**
- POST `/positions/sync/intraday-tws` returns 202 + `job_id`; persisted `Job.job_type == "intraday.sync.tws"`.
- `get_handler("intraday.sync.tws")` returns `handle_intraday_sync_tws`.
- Handler invokes `run_intraday_sync` once and returns its counts dict (service stubbed).

**Verification:** Click the button (U6) → job enqueues → worker runs the handler against a real TWS session → tables populate.

---

### U4. Read-time overlay merge + intraday P&L in the TradeGroup endpoint

**Goal:** Compose the TradeGroup view from live overlay + FlexQuery fallback; expose intraday unrealized/realized/total with freshness.

**Requirements:** Correct totals for all four mutation cases; FlexQuery untouched; explicit freshness.

**Dependencies:** U1, U2. **Sequence last** (shared-file collision with the concurrent agent — rebase first).

**Files:**
- `src/services/intraday_overlay.py` (new, pure merge/PnL helper — unit-testable without HTTP)
- `src/api/routers/trade_groups.py` (call the helper inside the executions endpoint)
- `tests/services/test_intraday_overlay.py`

**Approach:**
- `intraday_overlay.py` exposes pure functions over already-loaded rows (no DB/HTTP):
  - `merge_positions(flex_rows, live_rows, quotes)` → list of unified position views: for each `(account, con_id)`, prefer live qty/`avg_cost`; mark from `latest_quote` (fallback flex `mark_price`); `source` flag (`live`/`settled`); `mark_ts`/`as_of`; `unrealized = mark·qty·mult − cost_basis(qty, avg_cost)` using the U2-resolved multiplier convention.
  - `merge_realized(settled_execs, live_execs)` → settled ∪ live, dropping live whose `ib_exec_id` ∈ settled.
- In the executions endpoint, after building `account_con_pairs` (existing), additionally load `live_positions` + `latest_quote` for those pairs and `live_executions` for the group's pairs, pass everything to the helper, and populate response fields.
- Extend the response model with: per-position `source`, `mark`, `mark_ts`, `live_unrealized`; top-level `intraday_unrealized_pnl`, `intraday_realized_pnl`, `intraday_total_pnl`, `marks_as_of` (newest `market_ts`), and keep the existing settled fields unchanged (additive — no breaking change to current consumers).

**Execution note:** Test the merge helper first with table-driven fixtures covering the four cases before wiring it into the endpoint.

**Patterns to follow:** Existing executions endpoint aggregation (`src/api/routers/trade_groups.py` ~line 667+); `_execution_realized_pnl` (`src/api/routers/trades.py:240`).

**Test scenarios:**
- *Add* (Covers the GLD example): flex row qty 110 @ cost A; live row qty 130 @ blended cost B; quote mark M → unified shows qty 130, cost B, `unrealized == M·130·mult − B·130·mult`, `source == "live"`.
- *Open-today*: no flex row, live row qty 20 → appears with live qty/cost/mark.
- *Reduce*: flex qty 100, live qty 80, one closing fill → open position shows qty 80; realized includes the fill's `realized_pnl`.
- *Net-close*: flex qty 50, no live row, a closing fill → not in open positions; realized includes the fill.
- *Fallback*: live tables empty (no sync yet) → totals equal today's settled-only behavior; `source == "settled"`, `marks_as_of is None`.
- *Realized dedup*: a live fill with `ib_exec_id` also in settled execs is excluded from `merge_realized` (no double count).
- *Stale mark*: `latest_quote` row missing for a live position → mark falls back to flex `mark_price`; `source` still reflects live qty.

**Verification:** Against the prod DB + a live sync, the "Rolling Diagonals" group shows qty 130 GLD with live unrealized; settled totals match the pre-change endpoint when no live data is present.

---

### U5. (Optional) Portfolio-level overlay on the Positions page

**Goal:** Show the same live current-state merge on the main Positions view, so positions opened today (not yet tagged to any group) are visible intraday.

**Dependencies:** U4 (reuses `intraday_overlay.merge_positions`).

**Files:**
- `src/api/routers/positions.py`
- `frontend/src/components/PositionsTable.tsx`

**Approach:**
- Add overlay fields to the positions list endpoint by reusing `merge_positions` over all `live_positions` + `latest_quote` (not group-scoped). Additive response fields; existing behavior unchanged when no live data.
- Frontend shows live qty/mark/unrealized with the same freshness indicator.

**Patterns to follow:** U4; existing positions list endpoint + `PositionsTable.tsx`.

**Test scenarios:**
- A position opened today (no flex row) appears in the positions list when live data is present.
- With no live data, the list matches current FlexQuery-only behavior.

**Verification:** Open Positions page after an intraday sync; today's new position is listed with a live mark.

---

### U6. Frontend: refresh button + intraday P&L display

**Goal:** Trigger the sync and show live P&L alongside the settled snapshot on the TradeGroup view.

**Dependencies:** U3 (route), U4 (response fields).

**Files:**
- `frontend/src/components/TradeTaggingPage.tsx`

**Approach:**
- Add a "Refresh live (TWS)" button that POSTs `/positions/sync/intraday-tws`, toasts the queued job id, and refreshes the view after the job completes (reuse existing kickoff + poll/refresh pattern).
- In the P&L summary and OPEN POSITIONS table, display the intraday fields (`intraday_unrealized_pnl`, `intraday_realized_pnl`, `intraday_total_pnl`, per-row live `mark`/`unrealized`) next to the settled values, with a freshness indicator: `live as of HH:MM` when `marks_as_of` is present, else `settled <as_of_date>`.
- No change to the settled columns; intraday is additive.

**Patterns to follow:** `kickOffPositionSync` / `kickOffTradesSync` and the existing P&L summary + OPEN POSITIONS rendering in `TradeTaggingPage.tsx`.

**Test scenarios:** *Test expectation: none beyond manual smoke — presentational React change.* Manual: click refresh → 202 toast → after worker run, OPEN POSITIONS shows live qty 130 GLD and a `live as of` timestamp; with no live data, view shows settled values and `settled <date>`.

**Verification:** Browser network tab shows the POST; after the worker runs, intraday P&L and freshness render; settled values unchanged when no sync has run.

---

## System-Wide Impact

- **New TWS session dependency (intraday only).** The overlay requires TWS/Gateway reachable during market hours. FlexQuery sync remains session-free; if no TWS session is available, the overlay simply shows no live data and the view degrades to settled values. Document in `docs/workers.md` / getting-started.
- **Market-data subscriptions.** `reqTickers` on all held conids consumes IBKR market-data lines; manual-trigger keeps this bounded. Note line-count limits for accounts with many positions.
- **Settle handoff.** Tomorrow's FlexQuery sync ingests today's fills as settled `trade_executions`; the next intraday sync purges the now-settled `live_executions` by `ib_exec_id`. No manual cleanup.
- **Concurrent-agent collision.** U4 and U6 touch `src/api/routers/trade_groups.py` and `TradeTaggingPage.tsx`, which the other active agent may also edit — rebase before these units.
- **Docs index rule (AGENTS.md).** If a new `docs/*.md` is added for this feature, update `docs/_index.md` in the same change.

## Risks & Mitigations

- **Risk: IBKR `avgCost` multiplier semantics produce wrong cost basis** (per-share vs per-contract incl. multiplier varies by sec type). **Mitigation:** U2 deferred verification against known futures/equity/option positions vs TWS UI; encode the resolved convention once in `intraday_overlay.py`; the multiplier-sanity test guards regressions.
- **Risk: double-counting realized across the settle boundary.** **Mitigation:** dedup by `ib_exec_id` (unique on both `TradeExecution` and `LiveExecution`); `merge_realized` drops settled-duplicates; sync purges them.
- **Risk: brand-new instrument opened today shows in portfolio but not in its eventual TradeGroup.** **Mitigation:** documented limitation; U5 surfaces it at portfolio level; group association follows post-settle tagging (deferred auto-association).
- **Risk: stale/half-populated marks mislead.** **Mitigation:** explicit per-row `source` flag + `marks_as_of` timestamp; null mark falls back to settled snapshot mark rather than showing zero.
- **Risk: concurrent-agent merge conflicts on shared files.** **Mitigation:** sequence U4/U6 last; rebase before editing; the bulk of the feature is new files.

## Alternative Approaches Considered

- **Marks-only overlay on the stale snapshot (rejected).** Layering live marks onto FlexQuery quantities cannot represent positions opened today, nor added/reduced sizes — fails the four-case requirement. Sourcing current state from `ib.positions()` is what makes the overlay correct.
- **Snapshot + reconstruct-from-fills for current quantity (rejected as primary).** Hand-summing today's fills onto the snapshot duplicates TWS's own position accounting and owns every lot/dedup edge case. `ib.positions()` returns the reconciled current state directly. Fills are still needed — but only for *realized* attribution, not quantity.
- **Live columns on the `positions` table (rejected).** Would collide with the FlexQuery `(account_id, con_id)` unique constraint and mix live + settled in one row, violating "enhance, don't delete." Separate tables keep FlexQuery pure.
- **Reuse futures-only `latest_futures*` for marks (rejected).** Would force sec-type-specific routing and leave equities/equity-options unstorable. A unified `con_id`-keyed `latest_quote` covers all instruments per the chosen scope.
