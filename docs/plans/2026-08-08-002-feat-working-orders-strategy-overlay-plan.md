---
title: Working-Orders Strategy Overlay - Plan
type: feat
date: 2026-08-08
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: manual
execution: code
---

# Working-Orders Strategy Overlay - Plan

## Goal Capsule

- **Objective:** A strategy (trade group) shows not just where it _has been_ (settled trades) and where it _is_ (positions + intraday overlay), but where it **will be** once resting orders fill — so a resting far-from-market limit reads as "rebalance pending", not as invisible intent.
- **Authority hierarchy:** TWS is the sole source of truth for order state. The app never invents or mutates broker order state; the write path stays disabled (see [workers.md](../workers.md)).
- **Execution profile:** Vertical slices — every slice ships backend, worker, and frontend together and ends at something visible on `/orders` or the strategy view. Order: spike → order appears live → order resolves → legs → strategy link → projection → persistent subscription.
- **Stop conditions:** Stop and ask if S0 shows TWS returns combo orders in a shape the `order_legs` schema in S3 can't hold. Stop if any slice would require writing FlexQuery tables (`positions`, `trades`, `trade_executions`).
- **Tail ownership:** Standard repo flow — feature branch per slice, `task test`, PR with a demo-mode screenshot for UI phases.

---

## Product Contract

### Summary

The order-pull pipeline already exists end to end but was never verified against a live TWS session and has no concept of a strategy. This plan finishes it and then attaches it to trade groups, so the strategy view can render **current → working → projected** positioning. A resting order assigned to a strategy carries its assignment onto the fill automatically when it executes, reusing the live→settled carryover machinery that already exists for intraday fills.

### Problem Frame

The workflow the desk actually runs is: open a strategy, read its current positioning, decide the adjustment, place resting orders well outside the touch (below the ask when buying, above the bid when selling), then wait. Those orders may rest for hours or days.

During that wait the app is blind. The strategy view composes settled FlexQuery positions plus the intraday TWS overlay — both of which describe _filled_ state. A working order that would take a strategy from -3 to -1 is nowhere in the view. The operator cannot answer "have I already put in the adjustment for this strategy?" without switching to TWS and reading the order book by hand, mentally mapping each order back to a strategy.

Three concrete gaps block closing that loop:

**Orders don't reach the database reliably.** `sync_orders_with_ib` (`src/services/order_sync_tws.py`) exists and is wired from the Orders page button through `POST /api/v1/orders/sync` → `order.fetch_sync` → `handle_order_fetch_sync` (`src/workers/jobs.py:306`). There is no test coverage for it and no evidence it has run against a live session. It also never marks orders that _disappeared_ from TWS, so a row that was cancelled in TWS outside the completed-orders window stays `submitted` forever — a phantom "pending rebalance" that never resolves.

**Combos flatten to garbage.** An option spread entered in TWS returns a `BAG` contract carrying `comboLegs`. `_create_order_from_trade` writes a single `orders` row with one `symbol` and one `con_id`. A four-leg condor becomes one row that names no real contract and cannot be netted against any position. Since this desk trades spreads, the overlay is meaningless until legs are modeled. Note the settled and live _execution_ paths already handle this correctly via `exec_role` (`combo_summary` / `leg` / `standalone`) — the order path simply never got the same treatment.

**Orders have no strategy.** `orders` has no link to `trade_groups`. Executions have three (`trade_group_executions` for settled, `trade_group_live_executions` for unsettled fills, `trade_group_positions` for positions), and `src/services/group_link_carryover.py` already folds a live link onto its settled row at settlement. Orders need the same shape one step earlier in the lifecycle: assign at rest, carry onto the fill.

### Requirements

**Order fidelity**

- R1. Every working order visible in TWS — API-placed or hand-entered — appears in `orders` after a sync, including orders placed from other API clients.
- R2. A multi-leg order stores each leg with its own `con_id`, ratio, and action; the parent row identifies the combo, not a fabricated single contract.
- R3. An order that no longer exists at the broker stops reading as working. A sync that succeeds and does not observe a previously-working order marks it for reconciliation rather than leaving it `submitted` indefinitely.
- R4. Broker identity is stable and unique: `ib_perm_id` is the dedup key and is enforced as such.

**Strategy overlay**

- R5. A working order can be assigned to a trade group, and its legs net against that group's positioning.
- R6. The trade group view reports, per contract: current quantity, resting order quantity, and projected quantity if all working orders fill.
- R7. When a working order fills, its group assignment carries onto the resulting execution with no manual step and no double-count — the same guarantee `TradeGroupLiveExecution` provides today.
- R8. Unassigned working orders are discoverable, so intent placed in TWS never silently escapes the strategy model.

**Liveness**

- R9. Order state changes reach the browser without a manual refresh.
- R10. Order and execution events stream from a persistent IBKR subscription rather than depending solely on a polled fetch.

### Non-Goals

- Order submission or modification from the app. `scripts/work_order_queue.py` keeps its `RuntimeError` guard; see [spec-worker-order-recovery.md](../spec-worker-order-recovery.md).
- Cancel-from-UI against the broker. The existing `POST /orders/{id}/cancel` keeps its current local-only behavior.
- Automated strategy inference for orders. Assignment is explicit or heuristic-suggested, never silently applied.

---

## Slices

Each slice ships backend + worker + frontend together and ends at something visible
in the browser. No slice leaves a schema change stranded behind an unbuilt UI.
`S0` is the one exception — a spike with nothing to look at — and it is deliberately
kept to under an hour.

Demo mode currently has **no orders fixtures at all** (`frontend/src/lib/demoData.ts`
has none, `demoApi.ts` routes none), so S1 adds `demoOrders` plus the `/orders` route
and every later slice extends them. That is what makes the PR screenshots possible.

### S0 — Spike: what does TWS actually return? (no UI, no schema)

The combo shape decides S3's schema and the clientId answer decides S1's default.

- Add `scripts/dump_open_orders.py`: connects read-only, calls the same three fetches `_collect_recent_trades` uses (`reqOpenOrders`, `reqAllOpenOrders`, `reqCompletedOrders(apiOnly=False)`), and prints the structure of every returned `Trade` — contract fields, `comboLegs`, `orderStatus`, `permId`, `parentId`, `ocaGroup`, `orderRef`.
- Output must be anonymized per [ibkr-sample-data.md](../ibkr-sample-data.md) before anything lands in the repo. Real conids and account IDs stay out of the transcript and out of git.
- The clientId hypothesis is already narrow. `reqAutoOpenOrders` binds only orders created in TWS _after_ the call, requires clientId 0, and ib_async invokes it automatically on connect at id 0 — so the explicit call in `order_sync_tws.py:95` is redundant and cannot reach an order that was already resting. ib_async's own `reqAllOpenOrders` docstring points at the **Master API client ID** mechanism instead. Compounding it, `IBSessionPool` drops sessions idle past `--ib-idle-seconds` (300s default), so any autoBind is gone between syncs.
- So the one thing to test: set TWS _Global Config → API → Settings → Master API client ID_ to the sync client id, place a hand-entered order, disconnect, reconnect, confirm it comes back from `reqAllOpenOrders`. If it does, R1 is a configuration step plus a documented default, not code. Also confirm id 0 does not collide with the jobs worker's other pooled sessions (31–41, 141, and `BROKER_TWS_CLIENT_ID`=10).
- Record whether any observed `permId` exceeds int32 — it decides the column width in S1.

**Exit:** a written record of the real payload shape for a single-leg order and a multi-leg spread, plus a decided clientId strategy.

### S1 — A hand-entered TWS order shows up, live

The smallest end-to-end win: place a limit order in TWS, watch it appear on `/orders`
without touching the browser.

- **Backend.** Normalize `permId` 0 → NULL — `_create_order_from_trade` (`order_sync_tws.py:224`) stores `parse_int(permId)` verbatim and TWS reports `0` until it acks, so a partial unique index would fail on the second unacked order (line 296 already treats `0` as falsy). Widen `orders.ib_perm_id` (`models.py:279`) and `live_executions.ib_perm_id` (`:959`) from `Integer` to `BigInteger` to match `trades` / `trade_executions` (`:387`, `:427`) — S4 keys the whole carryover on permId across all three, so this is cheap now and a data migration later. Dedup existing rows (duplicate permIds are already possible: matching resolves `ORDER BY updated_at DESC LIMIT 1`), then add the partial unique index. Snapshot per [db-snapshots.md](../db-snapshots.md) first — this migration is not additive. Reorder `_find_matching_order` (`:143`) to permId-first, and guard the orderRef fallback: it resolves `ngtrader-order-<id>` straight to `session.get(Order, id)` with no check the row belongs to that broker order, so a recycled ref clobbers an unrelated one.
- **Worker.** Return created/updated order ids from `sync_orders_with_ib` (`:447`) and POST them to the existing `POST /events/notify-order`. `scripts/work_jobs.py:46` already has `_notify_api` doing exactly this for jobs/trades/positions — ~20 lines against a working pattern. This is R9, and there is no reason it should wait on S6.
- **Frontend.** Add `demoOrders` to `demoData.ts` and the `/orders` route to `demoApi.ts`. Drop the sync button's 1s `setTimeout` re-fetch (`OrdersTable.tsx:211`) — it races a job whose TWS connect timeout is 20s; the SSE event is the refresh now. Surface sync outcome instead of guessing: job state and a "last synced" timestamp.
- **Tests.** `tests/` has no order-sync coverage at all. Fake `Trade` objects exercise create / update / dedup / permId-0 with no TWS session. Highest-value item in the slice — S0 is manual and unrepeatable.

**See it:** place a limit order in TWS → the row appears on `/orders` with no manual refresh, named correctly, under the Working filter. Sync twice more → still one row.

### S2 — An order cancelled in TWS stops reading as working

- **Backend.** Stale sweep in `sync_orders_with_ib`: on a _successful_ fetch, working-status orders not observed in the batch get `last_seen_at` aged and transition to `reconcile_required` past a threshold. Never sweep on a fetch that errored or returned nothing — a dead session must not blank the book. Add `last_seen_at` and `ib_client_id` as nullable columns.
- `reconcile_required` already exists (`order_queue.py:23`, transitions at `:51` and `:60`) — no state-machine work.
- **Frontend.** This is the half that makes R3 real: `WORKING_STATUSES` (`OrdersTable.tsx:49-55`) currently counts `reconcile_required` as working, so sweeping without a UI change just converts a phantom `submitted` into a phantom `reconcile_required`. Give it its own filter bucket and a visually distinct badge.

**See it:** cancel the S1 order in TWS → after the next sync it leaves the Working count and shows as needing reconciliation, not as resting intent.

### S3 — Spreads render as legs

- **Backend.** New `order_legs` table: `order_id` FK, `con_id`, `ratio`, `action`, `exchange`, `open_close`, plus resolved display fields; unique on `(order_id, leg_index)`. Mark the parent row as a combo rather than pretending it is a single contract, reusing the `exec_role` vocabulary already in `LiveExecution` (`combo_summary` / `leg` / `standalone`) so order and execution paths read alike. Populate from `trade.contract.comboLegs` in `_create_order_from_trade` / `_sync_trade_onto_order`. Enrich unknown leg `con_id`s by enqueuing `contracts.qualify_and_snapshot` so `to_order_response` resolves names through `ContractRef` as it already does for single-leg orders.
- Strip `BAG` from the single-contract option path: `_derive_option_fields` (`api/routers/orders.py:118`) includes `BAG` in its sec_type set and regex-mines a strike out of the combo's localSymbol, so spreads render a fabricated strike today.
- Stop clamping quantity: `_safe_quantity` (`order_sync_tws.py:167`) does `abs()`, rounds, and forces a minimum of 1 into an `Integer` column. Per-leg quantity is `totalQuantity × ratio` signed by `leg.action` — the top risk in this plan. Store raw `totalQuantity` as a float, derive signs from leg actions, and add an explicit `remaining` (quantity − filled); nothing exposes remaining quantity today and S5 needs it.
- **Frontend.** Extend `OrderResponse` with legs; render a combo as a parent row with expandable legs in `OrdersTable.tsx`. Add a spread to the demo fixtures.

**See it:** enter a spread in TWS → every leg appears named correctly under one parent row, with per-leg signed quantities that match the ticket.

### S4 — Assign a working order to a strategy

- **Backend.** New `trade_group_orders` table modeled on `TradeGroupLiveExecution`: `trade_group_id` FK, unique `ib_perm_id`, denormalized `account_id`, `source`, `created_by`, `confidence`, `assigned_at`. Keying on `ib_perm_id` rather than `orders.id` is what makes carryover work — it is the one identifier shared by the resting order, the live fill (`live_executions.ib_perm_id`), and the settled execution (`trade_executions.ib_perm_id`). Assign/unassign endpoints mirroring the existing pair.
- Carryover: extend `src/services/group_link_carryover.py` so a fill bearing a `permId` with a `trade_group_orders` row creates the `trade_group_live_executions` (and ultimately `trade_group_executions`) assignment. Drop the order link once the order is terminal with no remaining quantity; partial fills keep the order link alive while also creating the fill link.
- **Frontend.** Assign-order-to-strategy control reusing `TradeGroupSearchSelect.tsx`; an unassigned-working-orders filter on `/orders` and a count badge on the strategies view (R8).

**See it:** assign a resting spread to a strategy from `/orders` → it disappears from the unassigned badge and appears in that strategy's working-orders list.

### S5 — Projection: current → working → projected

- **Backend.** Read model in `src/services/trade_group_pnl.py` (or a sibling): per `(account_id, con_id)` within a group, expose `current_quantity`, `working_quantity` (signed, from unfilled order/leg quantity), and `projected_quantity`. Read-time merge over settled + live + working — no new persisted aggregate, matching the intraday overlay's approach.
- **Frontend.** Working-orders section on the trade group view plus a projected-quantity column beside current quantity, visually distinct so a projection is never mistaken for a held position. Demo fixtures gain a projected position.

**See it:** a strategy at -3 with a resting order for +2 reads "current -3, working +2, projected -1", and the projection does not double-count a partial fill.

### S6 — Persistent subscription (R10)

- Convert `worker:orders` from a poll loop into a long-lived IBKR session subscribing to `openOrderEvent`, `orderStatusEvent`, and `execDetailsEvent`, writing order state and fills as they arrive. Settle during the slice: reconnect and backfill on session drop (a missed event window must be reconciled by a full fetch on reconnect, not assumed empty); clientId allocation against the S0 decision; and how streamed fills coexist with `intraday.sync.tws`, which already writes `live_executions` from `reqExecutions()` — one writer per table, or an explicit dedup rule on `ib_exec_id`. The polled `order.fetch_sync` job stays as the reconciliation path and the manual button.

**See it:** place an order in TWS and never touch the sync button — the row appears on `/orders` on its own within seconds.

## Sequencing Notes

- S0 gates S3 (payload shape decides leg schema) and S6 (clientId strategy).
- S1 gates S4 (`ib_perm_id` must be unique and wide enough before it can key a group link).
- S3 gates S5 (leg quantities are what net against positions).
- **"Working TWS orders visible on /orders" is S0 + S1 + S2 + S3.** S4–S5 are the strategy overlay and are separable; S6 is an upgrade to a path that already works by then.
- Each slice is its own branch, `task test`, and PR with a demo-mode screenshot.

## Risks

- **Combo leg quantity semantics.** A BAG order's `totalQuantity` is combo units; per-leg quantity is `totalQuantity × leg.ratio` with sign from `leg.action`. Getting this wrong silently corrupts every projected quantity. Verify against a known spread in S0 before writing the projection.
- **The stale sweep is destructive-adjacent.** A bug that sweeps on a failed fetch would blank the working book. Gate it on an explicit success signal from the fetch, and make the transition `reconcile_required` (recoverable) rather than `cancelled` (terminal).
- **Double-count on partial fills.** The projection reads three layers that can each describe the same contracts. Partial fills are the case where working and filled overlap; test it explicitly.
- **Test coverage is thin here.** `tests/` has no order-sync test at all. S1 adds one before the surface grows.
- **The S1 migration touches live prod rows.** Dedup + column widening on `orders` is not additive. Snapshot first; the dedup rule (keep newest by `updated_at`, null the rest) needs to be stated in the migration docstring, not inferred.
- **`reconcile_required` reads as working in the UI.** Sweeping without the frontend change converts a phantom "submitted" into a phantom "reconcile_required" and R3 is not actually met.

## Docs to Update

- [workers.md](../workers.md) — `worker:orders` behavior change in S6; `order.fetch_sync` notes.
- [core/api-ux-sse.md](../core/api-ux-sse.md) — remove the "order sync events are currently broken" note once the R9 fix lands in S1; the consumer table also still lists `OrdersTable` as 3s polling when it is SSE with a reconnect re-fetch.
- [core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md) — the working layer joins current/settled as a third overlay.
- [trade-tagging.md](../trade-tagging.md) — order-to-group assignment joins the existing assignment surfaces.
- `docs/_index.md` per the docs index rule for any new current-state doc.
