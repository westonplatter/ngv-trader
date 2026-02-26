# Spec: Restore Order Fetching and Submission

## Goal

Restore safe, production-usable order fetching and order submission in small, mergeable increments.

## Scope

- Restore backend order mutation APIs.
- Restore worker-based order execution and recovery behavior.
- Restore broker order fetching/sync into local `orders` and `order_events`.
- Restore tradebot execution-capable tools.
- Restore frontend submit/cancel actions.
- Add production verification gates after each merge.

## Out of Scope

- New strategy logic.
- Multi-broker support.
- Major schema redesign beyond what is required for recovery and idempotency.

## Merge Plan

## Implementation Status (as of February 26, 2026)

- PR 1: implemented in code (`src/services/order_queue.py`, shared job constants).
- PR 2: implemented in code (`POST /api/v1/orders`, `POST /api/v1/orders/{order_id}/cancel`, idempotent create retries).
- PR 3: implemented in code in this branch:
  - restored `scripts/work_order_queue.py`
  - restored `worker:orders` task in `Taskfile.yaml`
  - startup reconciliation runs before claim loop
  - deterministic `orderRef=ngtrader-order-{id}` is set on submit and used on restart reconciliation
  - queued orders are claimed atomically as `submitting` before broker submit
- PR 6: implemented in code in this branch:
  - restored submit UI in `/orders` (`POST /api/v1/orders`) with account/symbol/side/qty/type/tif inputs
  - restored cancel controls in `/orders` for queued orders (`POST /api/v1/orders/{order_id}/cancel`)
  - added in-flight guards for submit/cancel to prevent rapid double-click duplicate requests
  - `/orders` refreshes after submit/cancel and continues periodic polling
  - read-only flow improvements remain in place (manual pull sync button + working/terminal filters)
- Additional results validated in this phase:
  - position ingestion path is confirmed working end-to-end ("pull down positions" succeeds)
  - contract qualification helpers now support both singular and batch entry points:
    - `_qualify_contract(ib, spec) -> Contract`
    - `_qualify_contracts(ib, specs) -> list[Contract]`
- PR 4: implemented in code in this branch:
  - added `src/services/order_sync.py` to fetch open/recent broker orders and reconcile into `orders` + `order_events`
  - added `order.fetch_sync` handler in `scripts/work_jobs.py`
  - `scripts/work_order_queue.py` now auto-enqueues `order.fetch_sync` after processing orders
  - added manual enqueue endpoint `POST /api/v1/orders/sync`
  - added Tradebot tool `enqueue_order_fetch_sync_job` so chat can trigger broker order sync
- PR 5: implemented in code in this branch:
  - restored Tradebot tools `preview_order` and `submit_order`
  - updated Tradebot system prompt to support execution workflows
  - added shared order mutation service (`src/services/order_mutations.py`) so Tradebot and API use the same create/idempotency/event lifecycle
  - added limit order support in worker submit path (`LMT` uses IB `LimitOrder`, `MKT` uses `MarketOrder`)
- PR 7: implemented — docs and ops alignment:
  - updated README.md with order execution workflow section
  - updated `docs/tradebot-workers.md` with `worker:orders` and `order.fetch_sync` handler
  - updated `docs/tradebot-chatbot.md` with `enqueue_order_fetch_sync_job` tool
  - updated `docs/_index.md` spec description to reflect all PRs complete

### PR 1: Domain Primitives

- Reintroduce execution-related service modules:
  - `src/services/order_queue.py`
- Re-add job type constants and shared primitives needed by later PRs.
- Keep runtime execution paths disabled in this PR.

Acceptance:

- Ruff, Pyright, and import checks pass.
- No production behavior change.

### PR 2: Order Mutation API

- Restore:
  - `POST /api/v1/orders`
  - `POST /api/v1/orders/{order_id}/cancel`
- Add request models and validation.
- Ensure every state transition writes an `order_events` row.

Acceptance:

- API can create and cancel orders in DB.
- No duplicate order rows from retries with identical request payload.

### PR 3: Worker Order Execution

- Restore `scripts/work_order_queue.py`.
- Re-enable `worker:orders` task in `Taskfile.yaml`.
- Implement queued-to-terminal execution lifecycle.
- Add startup reconciliation pass before claiming new work.
- Keep execution path free of pre-trade gate dependencies.

Acceptance:

- Orders move through expected statuses without pre-trade checks in the execution path.
- Restarting worker does not produce duplicate broker submissions.

### PR 4: Broker Order Fetching/Sync

- Add or restore job path for broker order fetch/sync.
- Reconcile open/recent broker orders into `orders` and `order_events`.
- Make sync idempotent by broker identifiers.

Acceptance:

- Re-running sync does not duplicate rows.
- Broker-state drift is reconciled in DB.

### PR 5: Tradebot Execution Tools

- Restore tool specs and handlers for:
  - `preview_order`
  - `submit_order`
- Update prompt text to allow execution workflows again.

Acceptance:

- Tradebot submit path produces same DB/event lifecycle as direct API.

### PR 6: Frontend Order Actions

- Restore submit/cancel UX in orders surfaces.
- Add in-flight button guards and refresh behavior.

Acceptance:

- UI actions map correctly to backend state transitions.
- Rapid-click does not double submit.

### PR 7: Docs and Ops Alignment

- Update README and tradebot/worker docs to match restored capabilities.
- Keep `docs/_index.md` aligned with file additions/changes.

Acceptance:

- Operator docs match production behavior.

## Production Verification Gates

Run after each PR deploy. Do not merge next PR until current gate passes.

### Common Baseline (Before Each Gate)

1. Confirm TWS/Gateway is connected to the intended production account.
2. Capture baseline snapshots:
   - `GET /api/v1/orders`
   - `GET /api/v1/jobs`
   - worker heartbeat status
3. Use minimum live size for all tests.

### Gate A (After PR 1)

1. Run static checks:
   - `uv run --with ruff ruff check`
   - `uv run --with pyright pyright`
   - `uv run python scripts/check.py`
2. Confirm no order execution behavior changed.

### Gate B (After PR 2)

1. Submit one tiny test order via API.
2. Cancel it via API.
3. Verify:
   - order row created once,
   - status transitions are correct,
   - events appended for each transition.

### Gate C (After PR 3)

1. Start `worker:orders`.
2. Submit one tiny market order.
3. Verify lifecycle and broker IDs are persisted.
4. Restart worker during active lifecycle and confirm no duplicate submit.

### Gate D (After PR 4)

1. Trigger order fetch/sync.
2. Re-run sync twice.
3. Verify idempotent updates and reconciliation behavior.

### Gate E (After PR 5)

1. Submit one tiny order through tradebot tools.
2. Verify lifecycle parity with direct API path.
3. Verify invalid requests fail with clear, safe errors.

### Gate F (After PR 6)

1. Submit and cancel through UI.
2. Verify UI reflects backend truth and no duplicate submits occur.

## Rollback Triggers

Rollback immediately if any occurs:

- Duplicate live submission for a single logical order.
- Missing broker identifiers after successful submission.
- Orders stuck in `submitting` without reconciliation progress.
- Incorrect account or instrument routing.

## Evidence to Capture Per Gate

1. Request/response payloads for submit and cancel.
2. Order row before and after action.
3. `order_events` sequence.
4. Worker logs around tested order IDs.
5. Broker-side confirmation evidence.
