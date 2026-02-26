# Tradebot Workers

## Purpose

Workers run as separate processes and consume DB queues.

- `worker:jobs` handles generic background jobs (`jobs` table).
- `worker:orders` polls queued orders and submits them to TWS/Gateway.

## Construction

### Jobs Worker

- Entrypoint: `scripts/work_jobs.py`
- Queue primitive: `src/services/jobs.py`
- Current handler map:
  - `positions.sync` -> `src/services/position_sync.py`
  - `contracts.sync` -> `src/services/contract_sync.py`
  - `watchlist.add_instrument` -> `src/services/watchlist_instrument_sync.py`
  - `watchlist.quotes_refresh` -> `src/services/watchlist_quotes.py`
  - `order.fetch_sync` -> `src/services/order_sync.py`
- Claims queued jobs, runs handler, writes `result`/`status`, retries until `max_attempts`.

### Orders Worker

- Entrypoint: `scripts/work_order_queue.py`
- Queue primitive: `src/services/order_queue.py`
- Shared mutation service: `src/services/order_mutations.py`
- Polls `orders` table for queued orders and submits them to TWS/Gateway.
- Supports `MKT` (market) and `LMT` (limit) order types.
- Sets deterministic `orderRef=ngtrader-order-{id}` on each submission for deduplication.
- Runs startup reconciliation before claiming new work to prevent duplicate broker submissions after restart.
- After processing orders, auto-enqueues `order.fetch_sync` and `positions.sync` jobs.
- Status lifecycle: `queued` -> `submitting` -> `submitted` -> `partially_filled`/`filled`/`rejected`/`failed`.

## Heartbeats and Health

- Heartbeats stored in `worker_heartbeats`.
- Helper: `src/services/worker_heartbeat.py`
- API status endpoint: `GET /api/v1/workers/status`
- UI header lights map heartbeat freshness to green/yellow/red.

## Data Flow

1. Chat/API enqueues a row in `jobs`.
2. `worker:jobs` claims the job and performs the side effect (for example positions/contracts sync).
3. Worker updates lifecycle fields and timestamps.
4. UI polls tables and displays queue/run/total timing.

## Start Commands

```bash
ENV=dev task worker:jobs
ENV=dev task worker:orders
```

The commands run under `op run --env-file=.env.<env>` to resolve `op://` references.

## Key Files

- `scripts/work_jobs.py`
- `scripts/work_order_queue.py`
- `src/services/jobs.py` (includes `JOB_TYPE_WATCHLIST_QUOTES_REFRESH`)
- `src/services/position_sync.py`
- `src/services/contract_sync.py`
- `src/services/watchlist_instrument_sync.py`
- `src/services/watchlist_quotes.py`
- `src/services/order_queue.py`
- `src/services/order_sync.py`
- `src/services/order_mutations.py`
- `src/services/worker_heartbeat.py`
- `src/api/routers/workers.py`
