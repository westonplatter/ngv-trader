# Spec: SSE for Jobs and Orders UI Updates

## Problem

The frontend currently polls multiple endpoints on short intervals for jobs, orders, worker status, and related views. This causes unnecessary HTTP churn, duplicate fetches across components, and delayed UI updates between polling ticks.

Current examples:

1. Jobs polling every 2.5s in the jobs table
2. Orders polling every 2.5-3s in orders views
3. Worker status polling every 4s
4. Multiple components polling the same resource independently

## Goals

1. Replace high-frequency polling for jobs and order status with server-push updates.
2. Keep existing REST endpoints for initial page load and fallback refresh.
3. Minimize backend and frontend complexity.
4. Support local single-user operation first.
5. Avoid introducing a full bidirectional socket protocol when the main need is server-to-client updates.

## Non-Goals

1. Realtime streaming for market data quotes.
2. Full event sourcing of every entity in the system.
3. Multi-tenant pub/sub infrastructure.
4. Removing all polling everywhere in one change.

## Decision

Use Server-Sent Events (SSE) for jobs and orders.

Rationale:

1. The dominant data flow is server to browser.
2. FastAPI can support SSE with less surface area than WebSockets.
3. Browser consumption is simple via `EventSource`.
4. Existing REST endpoints can remain the system of record for initial state and manual reloads.
5. Reconnect behavior is built into the browser EventSource model.

## Scope

Phase 1 covers:

1. `jobs`
2. `orders`
3. worker status lights if they can be derived from pushed job/order/heartbeat events

Phase 1 does not cover:

1. trades
2. positions
3. watch lists
4. chat streaming

## Current State

Frontend components currently poll independently:

1. `frontend/src/components/JobsTable.tsx`
2. `frontend/src/components/OrdersTable.tsx`
3. `frontend/src/components/OrdersSideTable.tsx`
4. `frontend/src/components/WorkerStatusLights.tsx`
5. `frontend/src/components/MarketDataPage.tsx`

This creates:

1. duplicated requests
2. inconsistent refresh timing between panels
3. unnecessary work when tabs are hidden or idle

## Proposed Architecture

Use a hybrid model:

1. Initial snapshot via REST
2. Incremental updates via SSE
3. Periodic low-frequency REST fallback only for resilience, not primary freshness

### Backend

Use FastAPI's built-in SSE support (`fastapi.sse.EventSourceResponse` and `ServerSentEvent`, added in FastAPI 0.135.0) with an in-process event broadcaster.

Prerequisite: upgrade FastAPI from 0.129.0 to ≥0.135.0 (`uv add "fastapi>=0.135"`).

FastAPI handles automatically:

1. keepalive pings every 15 seconds
2. `Cache-Control: no-cache` header
3. `X-Accel-Buffering: no` header (prevents Nginx buffering)

Core pieces:

1. `src/services/ui_events.py`
   1. lightweight in-memory async pub/sub broker
   2. supports channels like `jobs`, `orders`, `worker_status`
   3. no manual serialization needed — `ServerSentEvent(data=...)` accepts Pydantic models directly
2. SSE API router
   1. `GET /api/v1/events/stream`
   2. optional query `topics=jobs,orders`
   3. uses `EventSourceResponse` as `response_class`
   4. yields `ServerSentEvent` instances with `data`, `event` fields
3. publisher hooks in existing mutation/sync flows
   1. job enqueue
   2. job status transitions
   3. job archive (via `PUT /api/v1/jobs/{id}/archive`)
   4. order create/update/cancel/sync
   5. worker heartbeat changes if exposed

### Frontend

Add a shared SSE client/store layer instead of per-component polling.

Core pieces:

1. `frontend/src/lib/events.ts`
   1. opens one `EventSource`
   2. handles reconnect state
   3. fans out events to subscribers
2. resource stores or hooks
   1. `useJobsStream`
   2. `useOrdersStream`
   3. optional `useWorkerStatusStream`
3. existing tables consume shared state instead of calling `fetch` on intervals

## API Design

### Endpoint

`GET /api/v1/events/stream?topics=jobs,orders`

Response:

1. `Content-Type: text/event-stream`
2. `Cache-Control: no-cache`
3. `Connection: keep-alive`

### Event Envelope

Use a consistent envelope for all topics.

```json
{
  "topic": "orders",
  "event": "updated",
  "entity_id": 123,
  "occurred_at": "2026-03-11T15:04:05Z",
  "version": 1,
  "payload": {}
}
```

Required fields:

1. `topic`: `jobs`, `orders`, `worker_status`
2. `event`: semantic event type
3. `entity_id`: nullable for aggregate/system events
4. `occurred_at`: UTC ISO timestamp
5. `version`: payload schema version
6. `payload`: resource-specific body

### Event Types

Jobs:

1. `job.created`
2. `job.updated`
3. `job.archived`

Orders:

1. `order.created`
2. `order.updated`
3. `order.cancelled`

Worker status:

1. `worker.heartbeat`
2. `worker.stale`
3. `worker.recovered`

### Payload Strategy

Use full response DTO payloads for Phase 1, not patches or raw DB rows.

SSE payloads must match the same shape returned by the corresponding REST endpoints. For orders this means the enriched `OrderResponse` projection (with `account_alias`, `contract_display_name`, `option_right`, `option_strike`, contract dates, etc. from `to_order_response()`), not the raw `Order` model. For jobs this means the same shape returned by `GET /api/v1/jobs`.

Reason:

1. simpler client logic — SSE rows are drop-in replacements for REST rows
2. no shape drift between REST snapshot and SSE updates
3. low event volume for this app
4. easier debugging
5. avoids drift from partial patch application bugs

Example order event:

```json
{
  "topic": "orders",
  "event": "order.updated",
  "entity_id": 123,
  "occurred_at": "2026-03-11T15:04:05Z",
  "version": 1,
  "payload": {
    "id": 123,
    "account_id": 1,
    "account_alias": "paper-1",
    "status": "filled",
    "symbol": "CL",
    "sec_type": "FUT",
    "contract_display_name": "CL Jul 2026",
    "side": "SELL",
    "filled_quantity": 1.0,
    "avg_fill_price": 2.31,
    "option_right": null,
    "option_strike": null,
    "updated_at": "2026-03-11T15:04:05Z"
  }
}
```

## Backend Design Details

### SSE Endpoint Implementation

Use `EventSourceResponse` and `ServerSentEvent` from `fastapi.sse`:

```python
from collections.abc import AsyncIterable
from fastapi import APIRouter
from fastapi.sse import EventSourceResponse, ServerSentEvent

router = APIRouter()

@router.get("/events/stream", response_class=EventSourceResponse)
async def stream_events(
    topics: str = "jobs,orders",
) -> AsyncIterable[ServerSentEvent]:
    subscriber = broadcaster.subscribe(topics.split(","))
    try:
        async for event in subscriber:
            yield ServerSentEvent(
                data=event.payload,    # response DTO (Pydantic model) — serialized automatically
                event=event.event,     # e.g. "job.updated", "order.created"
            )
    finally:
        broadcaster.unsubscribe(subscriber)
```

### Broadcaster

Use an in-memory async subscriber registry.

Behavior:

1. each SSE connection gets an async queue
2. publisher writes typed events into matching subscriber queues
3. disconnect removes the queue
4. keepalive pings are handled automatically by FastAPI (every 15s)

This is sufficient for the current single-app-process deployment style.

Constraint:

If the app later runs across multiple API processes, in-memory broadcast will not fan out across processes. At that point move the broker to Redis pub/sub or Postgres LISTEN/NOTIFY.

### Publish Points

Publish after successful commit, not before.

Required publish points:

1. `enqueue_job`
2. job worker state transitions
3. job archive (`PUT /api/v1/jobs/{id}/archive` in `src/api/routers/jobs.py`)
4. order create/update/cancel mutations
5. broker order sync updates

Rule:

The SSE event must reflect committed DB state. Do not emit pre-commit optimistic events from the backend.

### Snapshot and Reconciliation

Client flow:

1. fetch initial `GET /jobs` or `GET /orders`
2. open SSE stream
3. merge incoming full-row updates by `id`
4. optionally run a slow background reconciliation fetch every few minutes

Phase 1 does not support event replay on reconnect. The in-memory broadcaster has no retained event log. On reconnect, the client re-fetches the REST snapshot and resumes receiving live events. Replay support (via `Last-Event-ID` and an event log) is deferred until there is evidence of missed-update problems.

## Frontend Design Details

### Connection Model

Use one shared EventSource per browser tab, not one per component.

Benefits:

1. fewer open connections
2. one reconnect policy
3. easier debugging
4. no duplicate event handling

### State Update Rules

Jobs/orders stores should:

1. insert unseen rows
2. replace rows with matching `id`
3. preserve current sorting/filtering in view components
4. support manual `refresh()` with existing REST endpoint

### Fallback Behavior

If SSE is disconnected:

1. show subtle connection status in the UI
2. fall back to low-frequency polling, for example every 30s
3. stop fallback polling once SSE reconnects

## Worker Status Lights

Preferred direction:

1. drive worker lights from heartbeat events if available
2. otherwise keep current low-frequency polling in Phase 1

Do not block jobs/orders SSE rollout on worker status redesign.

## Security and Access

For current local usage, reuse existing API auth assumptions.

Minimum requirements:

1. same-origin only
2. no caching
3. bounded queue sizes per client
4. drop disconnected subscribers promptly

## Operational Concerns

### Keepalive

FastAPI's `EventSourceResponse` sends keepalive ping comments every 15 seconds automatically. No custom keepalive logic is needed.

### Backpressure

Per-client queues must be bounded.

If a client falls behind:

1. drop the connection
2. let the browser reconnect
3. rely on REST snapshot + new events to recover

### Logging

Log:

1. stream open
2. stream close
3. topic subscriptions
4. dropped slow subscribers
5. publish counts by topic

Avoid logging every keepalive tick.

## Alternatives Considered

### Keep Polling

Pros:

1. already works
2. simple mental model

Cons:

1. noisy HTTP traffic
2. duplicated polling logic
3. delayed UI freshness
4. extra DB/API load

### WebSockets

Pros:

1. bidirectional
2. flexible for future chat-like features

Cons:

1. more protocol surface than needed for jobs/orders
2. more frontend/backend connection logic
3. unnecessary for current one-way update flow

Decision:

WebSockets are not justified for Phase 1.

## Rollout Plan

### Sequential foundation (each step shapes the next)

1. Upgrade FastAPI to ≥0.135.0 for built-in SSE support.
2. Create in-memory async event broadcaster (`src/services/ui_events.py`).
3. Define shared SSE event envelope models (response DTOs, not raw DB rows).
4. Add SSE streaming endpoint (`GET /api/v1/events/stream`).

### Parallel tier 1 — backend publish hooks (subagents)

Run in parallel once the foundation is in place:

5a. Publish SSE events from job mutation paths (enqueue, state transitions, archive).
5b. Publish SSE events from order mutation paths (create, update, cancel, broker sync).

### Parallel tier 2 — frontend consumers (subagents)

Run in parallel once publish hooks and the shared EventSource client are in place:

6. Add frontend shared EventSource client (`frontend/src/lib/events.ts`).
   7a. Convert `JobsTable` to snapshot + SSE stream, remove 2.5s polling.
   7b. Convert `OrdersTable` and `OrdersSideTable` to shared orders store + SSE stream, remove 2.5-3s polling.
   7c. Optionally adapt `WorkerStatusLights` to SSE.

## Acceptance Criteria

1. Jobs table no longer polls every 2.5s when SSE is healthy.
2. Orders table no longer polls every 2.5-3s when SSE is healthy.
3. New/updated jobs appear in the UI without manual refresh.
4. Order status transitions appear in the UI without manual refresh.
5. A dropped SSE connection recovers automatically.
6. A disconnected client can recover via REST snapshot + new live events (no replay).
7. Existing REST endpoints remain usable for direct fetch and debugging.

## Open Questions

1. Should Phase 1 expose one multiplexed stream endpoint or separate `/jobs/stream` and `/orders/stream` endpoints?
2. Should worker status stay on polling in Phase 1?
3. Is single-process in-memory broadcast sufficient for expected deployment, or should Redis be planned now?
4. Do we want event IDs and replay support in Phase 1, or defer until there is evidence of missed-update problems?

## Recommendation

Implement a single multiplexed SSE endpoint with in-memory broadcast in Phase 1.

This is the smallest change that materially reduces API churn while preserving the current REST model and keeping the system easy to debug.
