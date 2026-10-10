---
title: "feat: Crash-safe order worker recovery"
type: feat
status: partial
created: 2026-02-24
artifact_contract: ce-unified-plan/v1
artifact_readiness: draft
product_contract_source: migrated-spec
execution: code
depth: standard
---

# feat: Crash-safe order worker recovery

> **Implementation status (verified 2026-10-10): scaffold only.** `orders`,
> `order_events`, `worker_heartbeats`, the status state machine, and a startup
> reconciliation pass (`reconcile_open_orders` in `scripts/work_order_queue.py`)
> exist. Order submission is hard-disabled: `scripts/work_order_queue.py` raises
> `"Order execution is not supported at this time."` before `placeOrder`. The
> crash-safety columns (`worker_id`, `lease_expires_at`, `order_ref`,
> `retry_count`, `max_retries`) and row-level claim locking are not in the
> `orders` schema. (`order_ref` exists on `trades` / `trade_executions` only, as
> the broker-reported value.)

## Goal Capsule

- **Objective:** `worker:orders` survives restarts and crashes without losing order state or duplicating a live order in TWS.
- **Authority hierarchy:** The DB lifecycle in `orders` / `order_events` is authoritative. TWS broker state wins during reconciliation; the worker never assumes an order is not live.
- **Execution profile:** Schema → transition guard → startup reconciliation → claim loop → submit path → shutdown/retry → UI.
- **Stop conditions:** Stop before removing the `placeOrder` guard. Enabling live submission is a separate, explicit decision.
- **Tail ownership:** Standard repo flow: Alembic migration via `task migrate`, `task test`, PR.

---

## Product Contract

### Summary

Productionize the order worker path: add lease/idempotency fields to `orders`, reconcile with TWS before claiming, claim with row locks, tag every IB order with a stable `orderRef`, and surface recovery state in the UI.

### Problem Frame

The worker can die mid-order. Without a lease and a stable broker-side idempotency key, a restarted worker cannot tell "never submitted" from "submitted but unrecorded", and a blind retry can double an order.

### Requirements

- R1. Every order has one authoritative lifecycle in the DB.
- R2. Worker crashes are recoverable; killing the worker mid-order loses no state.
- R3. Reboot never blindly re-submits a potentially live order.
- R4. Reconciliation runs before any new submission.
- R5. Every transition appends to `order_events`; fill data stays monotonic and auditable.
- R6. Recovery state (`reconcile_required`, stale lease, last event time) is visible in the API and UI.

Canonical states: `queued`, `submitting`, `submitted`, `partially_filled`, `reconcile_required`, and terminal `filled`, `cancelled`, `rejected`, `failed`.

### Non-Goals

- Strategy or risk model design.
- Multi-broker abstraction.
- Historical backfill outside active queued orders.
- Turning on live order submission.

---

## Planning Contract

### Key Technical Decisions

KTD1. **`order_ref = ngtrader-order-{id}` is the idempotency key.** Set as IB `orderRef` before submit, so reconciliation can match broker orders to DB rows even when `ib_order_id` was never persisted.

KTD2. **Lease-based claims.** `worker_id` + `lease_expires_at` + `heartbeat_at`. A hard-killed worker's rows become claimable when the lease expires; no coordinator needed.

KTD3. **Retry only on broker-confirmed absence.** A retry requires TWS to confirm no live order exists for that `order_ref`. Otherwise the row stays `reconcile_required`.

### Assumptions

- One active order worker in production; leases guard against overlap during deploys, not a fleet.
- Deploys drain the old worker before starting the new one.

---

## Implementation Units

### U1. Schema and model

**Requirements:** R1, R2

**Files:** `src/models.py` (`Order`), `alembic/versions/` (new migration)

**Approach:**

1. Add to `orders`: `worker_id`, `lease_expires_at`, `heartbeat_at`, `order_ref` (stable key), `retry_count`, `max_retries`, `reconcile_required`.
2. Index `(status, lease_expires_at, created_at)`.
3. Backfill `order_ref` for existing rows as `ngtrader-order-{id}` in the same migration.
4. Update the `Order` ORM model.

### U2. State transition guard

**Requirements:** R1, R5

**Approach:** A helper that validates every transition against the canonical state machine and appends the `order_events` row in the same transaction.

**Test scenarios:** Valid transitions pass; transitions out of terminal states are rejected; every accepted transition writes exactly one event.

### U3. Startup reconciliation

**Requirements:** R3, R4

**Files:** `scripts/work_order_queue.py` (extend `reconcile_open_orders`)

**Approach:**

1. Generate `worker_id` on boot; connect to TWS before entering the claim loop.
2. Load all non-terminal orders; mark stale `submitting` / `submitted` / `partially_filled` rows `reconcile_required`.
3. Pull TWS open-order and executions/fills snapshots.
4. Match by `order_ref`, falling back to `ib_order_id` / `ib_perm_id`.
5. Update matched rows to broker status, append reconciliation events, and close rows that are now terminal.
6. Leave unmatched non-terminal rows `reconcile_required`.

### U4. Claim loop and submit path

**Requirements:** R2, R3, R5

**Approach:**

1. Claim in a transaction with row-lock semantics, only `status IN (queued, reconcile_required)` with a null or expired lease.
2. On claim, set `worker_id`, `lease_expires_at`, `heartbeat_at`, and state `submitting`.
3. Heartbeat every loop while an order is active.
4. Set IB `orderRef` before submit; persist `ib_order_id` / `ib_perm_id` immediately after.
5. Move to `submitted` or `partially_filled`; append an event per status or fill delta.

### U5. Shutdown, crash, and retry

**Requirements:** R2, R3

**Approach:**

1. On SIGTERM, stop claiming, flush current progress, then disconnect TWS.
2. After a hard crash, lease expiry enables safe pickup; the rebooted worker reconciles first.
3. Retry only per KTD3. Mark permanently unresolved rows `failed` with an explicit reason.

### U6. Recovery visibility

**Requirements:** R6

**Approach:** Expose `reconcile_required`, stale lease, and last event timestamp through the orders API and UI.

---

## Verification Contract

| Gate          | Command                          | Applies to |
| ------------- | -------------------------------- | ---------- |
| Migration     | `task migrate ENV=dev`           | U1         |
| Imports       | `uv run python scripts/check.py` | all        |
| Backend tests | `task test`                      | U2–U5      |

Not command-shaped: kill the worker mid-order against a paper gateway and confirm reconciliation events appear on restart with no duplicate submission.

---

## Definition of Done

- Killing the worker mid-order does not lose order state.
- Reboot does not duplicate submission for the same order id.
- Fill data stays monotonic and auditable in `order_events`.
- The recovery path is visible in the API and UI.

---

## Risks & Dependencies

- **Live-money risk.** A reconciliation bug can duplicate a real order. The submission guard stays in place until this plan is verified on paper.
- **Operational rules:** run `worker:orders` continuously in production; drain the old worker on deploy; after an outage, restart and confirm reconciliation events. Orders stuck in `reconcile_required` after retries need a human.

---

## Open Questions

- What lease duration and heartbeat interval fit typical TWS round-trip latency?
- Who decides when to lift the `placeOrder` guard, and what sign-off does it need?

---

## Sources & Research

- `scripts/work_order_queue.py`: claim loop, `reconcile_open_orders`, submission guard.
- `src/models.py`: `Order`, `OrderEvent`, `WorkerHeartbeat`.
- `docs/workers.md`: worker topology.
- Migrated from `docs/spec-worker-order-recovery.md` (the original 42-step plan maps onto U1–U6).
