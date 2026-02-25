# Spec: Worker Order Recovery

## Purpose

Define how `worker:orders` survives restarts/crashes without losing state or duplicating live orders in TWS.

## Scope

- Order queue lifecycle in `orders` and `order_events`.
- Worker reboot and failover behavior.
- TWS reconciliation on startup.
- UI-visible progress and recovery state.

## Non-goals

- Strategy or risk model design.
- Multi-broker abstraction.
- Historical backfill outside active queued orders.

## Required Invariants

- Every order has one authoritative lifecycle in DB.
- Worker crashes are recoverable.
- Reboot never blindly re-submits a potentially live order.
- Reconciliation runs before new submissions.
- Every transition is appended to `order_events`.

## Canonical States

- `queued`
- `submitting`
- `submitted`
- `partially_filled`
- `filled` (terminal)
- `cancelled` (terminal)
- `rejected` (terminal)
- `failed` (terminal)
- `reconcile_required`

## 42-Step Plan

1. Add `worker_id` to `orders`.
2. Add `lease_expires_at` to `orders`.
3. Add `heartbeat_at` to `orders`.
4. Add `order_ref` to `orders` (stable idempotency key).
5. Add `retry_count` to `orders`.
6. Add `max_retries` to `orders`.
7. Add `reconcile_required` to `orders`.
8. Add index on `(status, lease_expires_at, created_at)`.
9. Update `Order` ORM model with new fields.
10. Backfill `order_ref` for existing rows as `ngtrader-order-{id}`.
11. Add state transition guard helper.
12. Add transition validation tests.
13. Worker starts and creates `worker_id` on boot.
14. Worker connects to TWS before claim loop.
15. Worker loads all non-terminal orders.
16. Worker marks stale `submitting/submitted/partially_filled` as `reconcile_required`.
17. Worker calls TWS open-order snapshot.
18. Worker calls TWS executions/fills snapshot.
19. Worker matches broker orders by `order_ref`.
20. Worker matches fallback by `ib_order_id`/`ib_perm_id`.
21. Worker updates matched DB rows with latest broker status.
22. Worker appends reconciliation events to `order_events`.
23. Worker closes rows now terminal (`filled/cancelled/rejected`).
24. Worker sets unmatched non-terminal rows to `reconcile_required`.
25. Worker enters claim loop after reconciliation.
26. Claim uses transaction with row lock semantics.
27. Claim only rows where `status in (queued,reconcile_required)`.
28. Claim only rows where lease is null or expired.
29. Claim sets `worker_id`, `lease_expires_at`, `heartbeat_at`.
30. Claim sets state to `submitting`.
31. Worker heartbeats every loop while order is active.
32. Worker sets IB `orderRef=ngtrader-order-{id}` before submit.
33. Worker persists `ib_order_id`/`ib_perm_id` immediately after submit.
34. Worker sets state to `submitted` or `partially_filled`.
35. Worker appends event each status/fill delta.
36. If worker receives SIGTERM, stop claiming new rows.
37. On SIGTERM, flush current order progress then disconnect TWS.
38. If worker dies hard, lease expiry enables safe pickup.
39. Rebooted worker reconciles first, then resumes claims.
40. Retry logic: only retry if broker confirms no live order for `order_ref`.
41. Mark permanently unresolved rows `failed` with explicit reason.
42. UI displays recovery flags (`reconcile_required`, stale lease, last event timestamp).

## Operational Rules

- Always run `worker:orders` continuously in production.
- On deploy, allow old worker to drain, then start new worker.
- If outage occurs, restart worker and verify reconciliation events appear.
- Manual intervention is required for orders stuck in `reconcile_required` after retries.

## Acceptance Criteria

- Killing worker mid-order does not lose order state.
- Reboot does not duplicate submission for same order id.
- Fill data remains monotonic and auditable in `order_events`.
- Recovery path is visible in API/UI.
