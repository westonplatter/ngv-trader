# Spec: Remove Order Execution Capability

## Goal

Remove all repo-managed paths that can place or queue live orders.

After this change, the system remains useful for:

- position sync
- contract sync and lookup
- read-only order/history visibility (optional, see scope)

## Why

- Reduce operational and financial risk from accidental or unintended execution.
- Keep this repo focused on observability, portfolio monitoring, and research workflows.

## Non-Goals

- Rebuilding execution in a safer subsystem.
- Dropping historical `orders` / `order_events` data in this phase.
- Removing IBKR connectivity required for non-execution workflows (positions/contracts).

## Status (as of February 23, 2026)

- Phase 1 complete:
  - direct execution CLI removed
  - order worker/task removed
  - order mutation API removed
  - tradebot execution tools removed
- Phase 2 complete:
  - `pretrade.check` job path removed
  - execution-only helper modules removed (`src/services/pretrade_checks.py`, `src/services/order_queue.py`)
- Phase 3 complete:
  - frontend cancel UX removed from orders views
  - worker status lights aligned to `worker:jobs` only
  - docs refreshed to reflect non-execution behavior

## Target State

- No code path calls broker order submit APIs (`ib.placeOrder`, `whatIfOrder`).
- No first-party UI/API/chat path can create, queue, submit, or cancel orders.
- Order history remains queryable (read-only) for audit/debug.
- Jobs worker continues for non-execution jobs.

## Scope Decisions

1. Keep read-only order visibility.

- Keep:
  - `GET /api/v1/orders`
  - `GET /api/v1/orders/{order_id}`
  - `GET /api/v1/orders/{order_id}/events`
- Remove or hard-disable all order mutation endpoints.

2. Keep schema tables for now.

- Keep `orders` and `order_events` tables to preserve history.
- Do not add destructive migrations in this phase.

3. Remove execution workers and tools completely.

- Delete execution worker/runtime surfaces instead of only hiding them in UI.

## Implementation Plan

### Phase 1: Immediate Execution Kill

1. Remove direct execution CLI.

- Status: complete.
- Deleted `scripts/execute_cl_buy_or_sell_continous_market.py`.
- Removed direct-execution references in docs and README.

2. Disable worker-based execution.

- Status: complete.
- Removed `worker:orders` task from `Taskfile.yaml`.
- Deleted `scripts/work_order_queue.py`.

3. Remove order mutation API.

- Status: complete.
- Removed create/cancel endpoints from `src/api/routers/orders.py`.
- Keep read-only list/detail/events endpoints.

4. Remove tradebot execution tools.

- Status: complete.
- Removed `preview_order`, `check_pretrade_job`, and `submit_order` from tool specs and handlers.
- Updated `_SYSTEM_PROMPT` to explicitly state execution is disabled.

### Phase 2: Execution Dependency Cleanup

1. Remove pretrade job path.

- Status: complete.
- Removed `JOB_TYPE_PRETRADE_CHECK` from `src/services/jobs.py`.
- Removed `handle_pretrade_check` and handler routing from `scripts/work_jobs.py`.
- Deleted `src/services/pretrade_checks.py`.

2. Remove now-unused execution helpers/imports.

- Status: complete.
- Deleted `src/services/order_queue.py` (no remaining imports).
- Removed stale imports/constants in API and tradebot service.

3. Keep read models stable.

- Status: complete.
- Kept `Order` / `OrderEvent` models and read APIs intact.

### Phase 3: UI + Docs Hardening

1. Frontend cleanup.

- Status: complete.
- Removed cancel actions from:
  - `frontend/src/components/OrdersTable.tsx`
  - `frontend/src/components/OrdersSideTable.tsx`
- Updated `TradebotChat` copy to remove order-queue wording.
- Updated worker status lights to monitor `worker:jobs` only.

2. Documentation updates.

- Status: complete for this decommission scope.
- Updated:
  - `README.md` goals/workflow/disclaimer wording that implied live execution
  - `docs/tradebot-chatbot.md`
  - `docs/tradebot-workers.md`
  - `docs/tradebot-langgraph-implementation.md`
  - `docs/contract-ref-setup.md`
  - removed legacy direct-execution runbook content

## Acceptance Criteria

1. No executable order submit path remains.

- `rg "ib\\.placeOrder|whatIfOrder"` returns no repo-owned execution path.

2. API cannot mutate orders.

- No `POST /api/v1/orders` route.
- No `POST /api/v1/orders/{order_id}/cancel` route.

3. Tradebot cannot request order placement.

- No `submit_order`, `preview_order`, or `check_pretrade_job` in tool specs/map.
- System prompt has no instruction to queue/submit orders.

4. Operator workflow has no order worker.

- `Taskfile.yaml` contains no `worker:orders`.
- `scripts/work_order_queue.py` is removed.

5. Static checks pass.

- `uv run --with ruff ruff check`
- `uv run --with pyright pyright`

## Rollout / Risk

- Rollout order:
  1. remove execution runtime paths first (Phase 1),
  2. then cleanup dependencies (Phase 2),
  3. then UI/docs polish (Phase 3).
- Primary risk: hidden internal references to removed tools/job types.
- Mitigation: fail-fast on startup/import errors via Ruff/Pyright and endpoint smoke checks.

## Open Questions

1. Should `orders` read APIs remain long-term, or be moved to an archived/audit-only surface?
2. Should we keep `Order`/`OrderEvent` schema indefinitely or schedule a later archive + drop migration?
3. Do we want a feature flag (`ENABLE_ORDER_EXECUTION=false`) as a temporary safety backstop during transition, or proceed with full hard-removal only?
