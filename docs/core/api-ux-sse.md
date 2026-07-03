# Server-Sent Events (SSE) for Real-Time UI Updates

How jobs, orders, and worker status flow from backend processes to the browser in real time using Server-Sent Events.

## Data Flow

```text
┌─────────────────┐  EventSource   ┌──────────────────┐           ┌──────────────┐
│  React Frontend │◀───────────────│  FastAPI Backend │──────────▶│  PostgreSQL  │
│  (Vite, :5173)  │  SSE stream    │  (Uvicorn, :8000)│           │  (:5432)     │
└─────────────────┘                └──────────────────┘           └──────────────┘
       │                             ▲            ▲                    ▲
       │ REST (initial               │            │                    │
       │  snapshot +                 │ notify-job │                    │
       │  actions)                   │ POST       │                    │
       ▼                             │            │                    │
┌─────────────────┐               ┌──┴────────────┴──┐          ┌──────┴───────┐
│  REST endpoints │               │  In-memory       │          │  Workers     │
│  /jobs, /orders │               │  Broadcaster     │◀─publish─│  (jobs,      │
│  /workers/status│               │  (ui_events.py)  │  via API │   orders)    │
└─────────────────┘               └──────────────────┘          └──┬────────┬──┘
                                                                   │        │
                                                          TWS sync │        │ Flex Query
                                                          (sync    │        │ (async HTTPS
                                                           socket) │        │  poll)
                                                                   ▼        ▼
                                                          ┌──────────────┐ ┌──────────────────┐
                                                          │ IBKR TWS /   │ │ IBKR Flex Query  │
                                                          │ IB Gateway   │ │ Web Service      │
                                                          │ (:7497)      │ │ (ndcdyn.ibllc... │
                                                          └──────────────┘ └──────────────────┘
```

IBKR data reaches the workers through two independent transports:

- **TWS / IB Gateway** — local socket connection on `:7497` used by `*_sync_tws.py` services (orders, and the TWS variants of trades/positions). Low-latency, session-bound, requires a running TWS/Gateway login.
- **Flex Query Web Service** — async HTTPS request/response against IBKR's hosted Flex Query API used by `*_sync_flexquery.py` services (trades, positions). The worker requests a report token, polls until the report is ready, then downloads and ingests the XML. No local broker session is required, but data is delayed (Flex Query refresh windows).

Both transports terminate in worker code that commits to PostgreSQL and then publishes SSE events through the same notify endpoints — the UI does not need to know which source produced a row.

### How an event reaches the browser

1. A **worker** completes a job (e.g. `market_data.futures_prices`), commits the result to PostgreSQL, then fires a best-effort `POST /api/v1/events/notify-job` to the API.
2. The **API process** reads the committed row from Postgres, builds the full response DTO (`JobResponse`), and pushes it into the **in-memory broadcaster**.
3. The broadcaster fans the event out to all **SSE subscriber queues** that match the topic.
4. The **SSE streaming endpoint** (`GET /api/v1/events/stream`) yields the event as a `ServerSentEvent` on the open HTTP connection.
5. The browser's **`EventSource`** receives the event, and the shared client in `frontend/src/lib/events.ts` dispatches it to the appropriate React hook (`useSSE`).
6. The **component** (e.g. `MarketDataPage`, `JobsTable`) merges the payload into its local state — the row updates in place without a full refetch.

### Two publish paths

| Source                                                      | How it publishes                                                                | When                                           |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------- | ---------------------------------------------- |
| **API endpoints** (create job, archive job, cancel order)   | Direct call to `broadcaster.publish()` in the same process, after `db.commit()` | Immediately after the mutation                 |
| **Workers** (job state transitions, heartbeats) | HTTP POST to `/api/v1/events/notify-job`, `/api/v1/events/notify-worker-status`, `/api/v1/events/notify-trades`, or `/api/v1/events/notify-positions` | After `session.commit()` in the worker process |

Workers run in a separate process from the API, so they cannot access the in-memory broadcaster directly. The notify endpoints bridge this gap.

## Architecture

### SSE stream endpoint

`GET /api/v1/events/stream?topics=jobs,orders,worker_status,trades,positions`

One multiplexed endpoint serves all topics. The browser opens a single `EventSource` connection per tab. FastAPI's `EventSourceResponse` sends a keepalive ping every 15s automatically; the route does not set `Cache-Control` or `X-Accel-Buffering` headers, so a reverse proxy in front of the API may need those configured separately to avoid buffering the stream.

### In-memory broadcaster (`src/services/ui_events.py`)

A lightweight async pub/sub broker running inside the API process:

- Each SSE connection gets a bounded async queue (max 256 items)
- Publishers write typed events into matching subscriber queues by topic
- Slow subscribers whose queues fill up are dropped (the browser reconnects automatically)
- Sufficient for single-process deployment; upgrade to Redis pub/sub or Postgres LISTEN/NOTIFY if the API scales to multiple processes

### Worker notification endpoints

| Endpoint                                   | Purpose                                                                              |
| ------------------------------------------ | ------------------------------------------------------------------------------------ |
| `POST /api/v1/events/notify-job`           | Worker sends `{ job_id, event }` after job state changes                             |
| `POST /api/v1/events/notify-order`         | Worker sends `{ order_id, event }` after order mutations                             |
| `POST /api/v1/events/notify-worker-status` | Worker sends `{ worker_type }` after heartbeat upserts                               |
| `POST /api/v1/events/notify-trades`        | Worker sends coarse hint after `trades.sync.flexquery` completes (triggers re-fetch) |
| `POST /api/v1/events/notify-positions`     | Worker sends coarse hint after `positions.sync.flexquery` completes (triggers re-fetch) |

The API reads the committed row, builds the enriched response DTO, and publishes to the broadcaster. Notifications are fire-and-forget from the worker side — if the API is unreachable, the UI catches up on the next REST fetch or SSE reconnect.

### Frontend SSE client (`frontend/src/lib/events.ts`)

A singleton `EventSource` manager shared across all components:

- Opens lazily on first subscriber, closes when all unsubscribe
- Fans out events to callbacks by topic
- Tracks connection status (`connecting` / `connected` / `disconnected`)
- Exposes `useSSE<T>(topic, onEvent)` React hook that returns connection status

## Event Envelope

All events use a consistent envelope:

```json
{
  "topic": "jobs",
  "event": "job.updated",
  "entity_id": 123,
  "occurred_at": "2026-03-14T00:13:51Z",
  "version": 1,
  "payload": {
    "id": 123,
    "job_type": "market_data.futures_prices",
    "status": "completed",
    "...": "..."
  }
}
```

| Field         | Description                                                |
| ------------- | ---------------------------------------------------------- |
| `topic`       | `jobs`, `orders`, `worker_status`, `trades`, or `positions` |
| `event`       | Semantic event type (see below)                            |
| `entity_id`   | Row ID, or null for system events                          |
| `occurred_at` | UTC ISO timestamp                                          |
| `version`     | Payload schema version (always 1 for now)                  |
| `payload`     | Full response DTO matching the corresponding REST endpoint |

### Event types

| Topic         | Events                                              | Payload shape                                      |
| ------------- | --------------------------------------------------- | -------------------------------------------------- |
| Jobs          | `job.created`, `job.updated`, `job.archived`        | Full `JobResponse` DTO                             |
| Orders        | `order.created`, `order.updated`, `order.cancelled` | Full `OrderResponse` DTO                           |
| Worker status | `worker.heartbeat`                                  | `WorkerStatusPayload`                              |
| Trades        | `trades.changed`                                    | Coarse hint (`{}`) — consumer should re-fetch      |
| Positions     | `positions.changed`                                 | Coarse hint (`{}`) — consumer should re-fetch      |

`jobs` and `orders` payloads are full response DTOs — drop-in replacements for REST rows with no shape drift. `trades` and `positions` events are coarse signals; `entity_id` is always `null` and the payload is empty (`{}`). Consumers re-fetch the REST snapshot on receipt.

### Event reference

| Event              | Topic           | Trigger                                         | Publisher                                     | Payload DTO           |
| ------------------ | --------------- | ----------------------------------------------- | --------------------------------------------- | --------------------- |
| `job.created`      | `jobs`          | `POST /api/v1/jobs` (UI enqueues a job)         | `src/api/routers/jobs.py`                     | `JobResponse`         |
| `job.created`      | `jobs`          | `POST /api/v1/orders/sync` (enqueue order sync) | `src/api/routers/orders.py`                   | `JobResponse`         |
| `job.updated`      | `jobs`          | Worker claims a job (queued → running)          | `scripts/work_jobs.py` via notify             | `JobResponse`         |
| `job.updated`      | `jobs`          | Worker completes a job (running → completed)    | `scripts/work_jobs.py` via notify             | `JobResponse`         |
| `job.updated`      | `jobs`          | Worker fails a job (running → failed/queued)    | `scripts/work_jobs.py` via notify             | `JobResponse`         |
| `job.archived`     | `jobs`          | `POST /api/v1/jobs/{id}/archive`                | `src/api/routers/jobs.py`                     | `JobResponse`         |
| `order.created`    | `orders`        | TWS broker sync discovers a new order           | `src/services/order_sync_tws.py` (calls `broadcaster.publish()` directly — see note below) | `OrderResponse` |
| `order.updated`    | `orders`        | TWS broker sync updates an existing order       | `src/services/order_sync_tws.py` (calls `broadcaster.publish()` directly — see note below) | `OrderResponse` |
| `order.cancelled`  | `orders`        | `POST /api/v1/orders/{id}/cancel`               | `src/api/routers/orders.py`                   | `OrderResponse`       |
| `worker.heartbeat`  | `worker_status` | Worker heartbeat upsert (every poll cycle)                      | `src/services/worker_heartbeat.py` via notify | `WorkerStatusPayload` |
| `trades.changed`    | `trades`        | `trades.sync.flexquery` job completes                           | `scripts/work_jobs.py` via notify             | `{}` (coarse hint)    |
| `positions.changed` | `positions`     | `positions.sync.flexquery` job completes                        | `scripts/work_jobs.py` via notify             | `{}` (coarse hint)    |

**Notify path**: Events marked "via notify" originate in the worker process. After committing to Postgres, the worker POSTs to a notification endpoint on the API (`/events/notify-job` or `/events/notify-worker-status`). The API reads the committed row, builds the response DTO, and publishes to the in-memory broadcaster. Events without "via notify" are published directly by the API process after its own `db.commit()`.

**Order sync events are currently broken in practice**: `order_sync_tws.py` runs inside the `worker:jobs` process (via `handle_order_fetch_sync`), not the API process, so its direct `broadcaster.publish()` call writes to a broadcaster instance with no SSE subscribers. Nothing in the codebase calls `POST /api/v1/events/notify-order` — the endpoint exists but is never invoked. `order.created`/`order.updated` events do not currently reach the browser; the UI catches up via the next REST fetch instead.

## Frontend Integration

### Client flow

1. Component mounts, fetches initial data via REST (`GET /jobs`, `GET /orders`, etc.)
2. `useSSE` hook subscribes to the relevant topic
3. On each SSE event, the component merges the payload by `id` (upsert or remove)
4. On SSE reconnect (status transitions from `disconnected` to `connected`), re-fetch the REST snapshot
5. Connection status badge shows in the component header

### Components using SSE

| Component            | Topic                                      | Replaces     |
| -------------------- | ------------------------------------------ | ------------ |
| `JobsTable`          | `jobs`                                     | 2.5s polling |
| `OrdersTable`        | `orders`                                   | 3s polling   |
| `OrdersSideTable`    | `orders`                                   | 2.5s polling |
| `MarketDataPage`     | `jobs` (filtered to market data job types) | 3s polling   |
| `WorkerStatusLights` | `worker_status`                            | 4s polling   |
| `PositionsTable`     | `positions` (coarse — triggers re-fetch)   | —            |
| `TradesTable`        | `trades` (coarse — triggers re-fetch)      | —            |
| `PricingPage`        | `jobs` (filtered to qualify/snapshot types) | —           |

### Merge rules

- **Insert** unseen rows (new `id`)
- **Replace** rows with matching `id`
- **Remove** on `job.archived` events (archived jobs are excluded from default views)
- Preserve current sorting and filtering in view components

## Key Files

| File                               | Purpose                                                                          |
| ---------------------------------- | -------------------------------------------------------------------------------- |
| `src/services/ui_events.py`        | Broadcaster singleton, event envelope model, `make_event()` helper               |
| `src/api/routers/events.py`        | SSE stream endpoint + worker notification endpoints                              |
| `src/api/routers/jobs.py`          | Publishes `job.created` and `job.archived` after API mutations                   |
| `src/api/routers/orders.py`        | Publishes `order.cancelled` after cancel; `job.created` after order sync enqueue |
| `src/services/order_sync_tws.py`   | Publishes `order.created` / `order.updated` after broker sync commit             |
| `src/services/worker_heartbeat.py` | Publishes `worker.heartbeat` after each heartbeat upsert                         |
| `scripts/work_jobs.py`             | Calls `POST /events/notify-job` after job state transitions                      |
| `frontend/src/lib/events.ts`       | Shared EventSource client with `useSSE` React hook                                                                                                               |

## Resilience

- **SSE reconnect**: `EventSource` reconnects automatically on disconnect. Components re-fetch the REST snapshot on reconnect.
- **Worker notifications**: Fire-and-forget. If the API is down when the worker finishes, the UI catches up when the SSE stream reconnects and re-fetches.
- **Backpressure**: Subscriber queues are bounded at 256 items. Slow clients are dropped; they reconnect and re-snapshot.
- **No replay**: The broadcaster has no retained event log. On reconnect, clients re-fetch via REST. Replay support (via `Last-Event-ID`) is deferred until there is evidence of missed-update problems.

## Future Considerations

- **Multi-process deployment**: Replace the in-memory broadcaster with Redis pub/sub or Postgres LISTEN/NOTIFY.
- **Additional topics**: Watchlists could be added as a new SSE topic using the same infrastructure.
- **Event replay**: Add `Last-Event-ID` support with a short event log if missed-update problems emerge.
