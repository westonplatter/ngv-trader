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

- **Objective:** A strategy (trade group) shows not just where it *has been* (settled trades) and where it *is* (positions + intraday overlay), but where it **will be** once resting orders fill — so a resting far-from-market limit reads as "rebalance pending", not as invisible intent.
- **Authority hierarchy:** TWS is the sole source of truth for order state. The app never invents or mutates broker order state; the write path stays disabled (see [workers.md](../workers.md)).
- **Execution profile:** Backend first, in the order: verify live → model combos → strategy link → projection → UI → event stream. Each phase leaves the system usable.
- **Stop conditions:** Stop and ask if P0 shows TWS returns combo orders in a shape the `order_legs` schema in P2 can't hold. Stop if any phase would require writing FlexQuery tables (`positions`, `trades`, `trade_executions`).
- **Tail ownership:** Standard repo flow — feature branch per phase, `task test`, PR with a demo-mode screenshot for UI phases.

---

## Product Contract

### Summary

The order-pull pipeline already exists end to end but was never verified against a live TWS session and has no concept of a strategy. This plan finishes it and then attaches it to trade groups, so the strategy view can render **current → working → projected** positioning. A resting order assigned to a strategy carries its assignment onto the fill automatically when it executes, reusing the live→settled carryover machinery that already exists for intraday fills.

### Problem Frame

The workflow the desk actually runs is: open a strategy, read its current positioning, decide the adjustment, place resting orders well outside the touch (below the ask when buying, above the bid when selling), then wait. Those orders may rest for hours or days.

During that wait the app is blind. The strategy view composes settled FlexQuery positions plus the intraday TWS overlay — both of which describe *filled* state. A working order that would take a strategy from -3 to -1 is nowhere in the view. The operator cannot answer "have I already put in the adjustment for this strategy?" without switching to TWS and reading the order book by hand, mentally mapping each order back to a strategy.

Three concrete gaps block closing that loop:

**Orders don't reach the database reliably.** `sync_orders_with_ib` (`src/services/order_sync_tws.py`) exists and is wired from the Orders page button through `POST /api/v1/orders/sync` → `order.fetch_sync` → `handle_order_fetch_sync` (`src/workers/jobs.py:306`). There is no test coverage for it and no evidence it has run against a live session. It also never marks orders that *disappeared* from TWS, so a row that was cancelled in TWS outside the completed-orders window stays `submitted` forever — a phantom "pending rebalance" that never resolves.

**Combos flatten to garbage.** An option spread entered in TWS returns a `BAG` contract carrying `comboLegs`. `_create_order_from_trade` writes a single `orders` row with one `symbol` and one `con_id`. A four-leg condor becomes one row that names no real contract and cannot be netted against any position. Since this desk trades spreads, the overlay is meaningless until legs are modeled. Note the settled and live *execution* paths already handle this correctly via `exec_role` (`combo_summary` / `leg` / `standalone`) — the order path simply never got the same treatment.

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

## Phases

### P0 — Verify against live TWS (spike, no schema change)

The combo shape decides P2's schema, so observation comes before design.

- Add `scripts/dump_open_orders.py`: connects read-only, calls the same three fetches `_collect_recent_trades` uses (`reqOpenOrders`, `reqAllOpenOrders`, `reqCompletedOrders(apiOnly=False)`), and prints the structure of every returned `Trade` — contract fields, `comboLegs`, `orderStatus`, `permId`, `parentId`, `ocaGroup`, `orderRef`.
- Output must be anonymized per [ibkr-sample-data.md](../ibkr-sample-data.md) before anything lands in the repo. Real conids and account IDs stay out of the transcript and out of git.
- Resolve the clientId question empirically. `handle_order_fetch_sync` defaults `client_id=0`, and `_collect_recent_trades` only calls `reqAutoOpenOrders(True)` at id 0. Determine which of `reqAllOpenOrders` vs. the id-0 binding actually surfaces hand-entered TWS orders on this setup, and whether id 0 conflicts with TWS's configured master client id or with the jobs worker's other pooled sessions (`BROKER_TWS_CLIENT_ID`, `BROKER_TWS_QUOTES_CLIENT_ID`).

**Exit:** a written record of the real payload shape for a single-leg order and a multi-leg spread, plus a decided clientId strategy. This is the input to P2.

### P1 — Single-leg correctness

- Migration: unique index on `orders.ib_perm_id` (partial, `WHERE ib_perm_id IS NOT NULL`); add `aux_price`, `oca_group`, `parent_perm_id`, `order_ref`, `ib_client_id`, `last_seen_at`.
- `_find_matching_order`: match on `ib_perm_id` first as the stable identity; keep `orderRef` and `ib_order_id` as fallbacks.
- Stale sweep in `sync_orders_with_ib`: on a successful fetch, working-status orders not observed in the batch get `last_seen_at` aged and transition to `reconcile_required` past a threshold. Never sweep on a fetch that errored or returned nothing — a dead session must not cancel the book.
- Backfill `ib_client_id` / `last_seen_at` as nullable; no mutation of existing rows.

**Exit:** a hand-entered TWS limit order appears in `orders`, survives repeated syncs without duplicating, and resolves out of "working" when cancelled in TWS.

### P2 — Combo/BAG legs

- New `order_legs` table: `order_id` FK, `con_id`, `ratio`, `action`, `exchange`, `open_close`, plus resolved display fields. Unique on `(order_id, leg_index)`.
- `orders` gains `exec_role`-parallel semantics: mark the parent row as a combo rather than pretending it is a single contract. Reuse the vocabulary already in `LiveExecution.exec_role` (`combo_summary` / `leg` / `standalone`) so the order and execution paths read alike.
- Populate legs in `_create_order_from_trade` / `_sync_trade_onto_order` from `trade.contract.comboLegs`.
- Enrich unknown leg `con_id`s by enqueuing `contracts.qualify_and_snapshot`, so `to_order_response` can resolve display names through `ContractRef` the way it already does for single-leg orders.
- Extend `OrderResponse` with legs; update `OrdersTable.tsx` to render a combo as a parent row with its legs.

**Exit:** a spread entered in TWS renders with every leg named correctly on the Orders page.

### P3 — Strategy link and projection

This is the phase the workflow actually needs; P0–P2 exist to make it truthful.

- New `trade_group_orders` table, modeled directly on `TradeGroupLiveExecution`: `trade_group_id` FK, unique `ib_perm_id`, denormalized `account_id`, `source`, `created_by`, `confidence`, `assigned_at`. Keying on `ib_perm_id` rather than `orders.id` is what makes carryover work — it is the one identifier shared by the resting order, the live fill (`live_executions.ib_perm_id`), and the settled execution (`trade_executions.ib_perm_id`).
- Assign/unassign endpoints mirroring the existing pair: `POST /trade-groups/{id}/orders:assign` and `:unassign`.
- Carryover: extend `src/services/group_link_carryover.py` so that when a fill arrives bearing a `permId` that has a `trade_group_orders` row, the resulting `trade_group_live_executions` (and ultimately `trade_group_executions`) assignment is created from it. Drop the order link once the order reaches a terminal status with no remaining quantity. Partial fills keep the order link alive while also creating the fill link — the projection must not double-count the filled portion.
- Projection read model in `src/services/trade_group_pnl.py` (or a sibling): per `(account_id, con_id)` within a group, expose `current_quantity`, `working_quantity` (signed, from unfilled order/leg quantity), and `projected_quantity`. This is a read-time merge over the settled + live + working layers — no new persisted aggregate, matching the intraday overlay's approach.
- Unassigned-working-orders surface for R8: a filter on the Orders page, plus a count badge on the strategies view.

**Exit:** assign a resting spread order to a strategy; the strategy shows current vs. projected positioning; on fill, the executions land in that strategy with no manual step.

### P4 — UI

- Trade group view gains a working-orders section and a projected-quantity column beside current quantity, visually distinct so a projection is never mistaken for a held position.
- Assign-order-to-strategy control reusing `TradeGroupSearchSelect.tsx`.
- Demo fixtures: add working orders and a projected position to `frontend/src/lib/demoData.ts` and route them in `demoApi.ts`, so the PR screenshot shows real content.

### P5 — Event stream (R9, R10)

Two distinct problems, addressed in order.

- **SSE plumbing (R9).** `order_sync_tws.py` calls `broadcaster.publish()` from inside the `worker:jobs` process, where no SSE subscriber exists — documented in [core/api-ux-sse.md](../core/api-ux-sse.md). `POST /api/v1/events/notify-order` exists and is never called. Wire the worker to post through it, matching whatever pattern the other workers use.
- **Persistent subscription (R10).** Convert `worker:orders` from a poll loop into a long-lived IBKR session subscribing to `openOrderEvent`, `orderStatusEvent`, and `execDetailsEvent`, writing order state and fills as they arrive. Design notes to settle during the phase: reconnect and backfill on session drop (a missed event window must be reconciled by a full fetch on reconnect, not assumed empty); clientId allocation against the P0 decision; and how streamed fills coexist with `intraday.sync.tws`, which already writes `live_executions` from `reqExecutions()` — one writer per table, or an explicit dedup rule on `ib_exec_id`. The polled `order.fetch_sync` job stays as the reconciliation path and the manual button.

---

## Sequencing Notes

- P0 gates P2 (payload shape decides leg schema) and P5 (clientId strategy).
- P1 gates P3 (`ib_perm_id` must be unique before it can key a group link).
- P2 gates P3's projection (leg quantities are what net against positions).
- P4 and P5's SSE half are independent of each other and can land in either order once P3 is in.

## Risks

- **Combo leg quantity semantics.** A BAG order's `totalQuantity` is combo units; per-leg quantity is `totalQuantity × leg.ratio` with sign from `leg.action`. Getting this wrong silently corrupts every projected quantity. Verify against a known spread in P0 before writing the projection.
- **The stale sweep is destructive-adjacent.** A bug that sweeps on a failed fetch would blank the working book. Gate it on an explicit success signal from the fetch, and make the transition `reconcile_required` (recoverable) rather than `cancelled` (terminal).
- **Double-count on partial fills.** The projection reads three layers that can each describe the same contracts. Partial fills are the case where working and filled overlap; test it explicitly.
- **Test coverage is thin here.** `tests/` has no order-sync test at all. P1 should add one before the surface grows.

## Docs to Update

- [workers.md](../workers.md) — `worker:orders` behavior change in P5; `order.fetch_sync` notes.
- [core/api-ux-sse.md](../core/api-ux-sse.md) — remove the "order sync events are currently broken" note once P5 lands.
- [core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md) — the working layer joins current/settled as a third overlay.
- [trade-tagging.md](../trade-tagging.md) — order-to-group assignment joins the existing assignment surfaces.
- `docs/_index.md` per the docs index rule for any new current-state doc.
