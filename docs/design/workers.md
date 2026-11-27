---
topics: ["workers", "jobs", "job-queue", "orders", "heartbeats"]
code_dirs_or_files:
  [
    "scripts/work_jobs.py",
    "src/workers/jobs.py",
    "src/services/jobs.py",
    "scripts/work_order_queue.py",
    "scripts/work_order_stream.py",
    "src/services/order_stream_tws.py",
    "src/services/order_worker.py",
    "src/services/worker_heartbeat.py",
  ]
description: Background workers and the job queue — jobs worker handler registry, dormant TWS handlers, disabled order submission, and heartbeat health.
---

# Workers

Background processes that run separately from the API and consume DB-backed
queues. Two workers consume queues; a third streams from TWS.

| Worker                | Entrypoint                     | Queue           | Status                                               |
| --------------------- | ------------------------------ | --------------- | ---------------------------------------------------- |
| `worker:jobs`         | `scripts/work_jobs.py`         | `jobs` table    | Active                                               |
| `worker:orders`       | `scripts/work_order_queue.py`  | `orders` table  | Scaffold only — **submission is disabled**           |
| `worker:order-stream` | `scripts/work_order_stream.py` | TWS push events | Off unless `ORDER_STREAM_ENABLED` is set (prod only) |

Start commands:

```bash
task worker:jobs
task worker:orders
task worker:order-stream
```

`ENV` defaults to `prod` (see `Taskfile.yaml`) — pass `ENV=dev` to target your local/dev environment instead: `ENV=dev task worker:jobs`.

## Jobs worker (`worker:jobs`)

The job logic lives in `src/workers/jobs.py` (handlers, the `get_handler`
dispatch table, and a shared `IBSessionPool`). `scripts/work_jobs.py` is a thin
CLI shim that claims queued jobs, runs the handler, writes `result`/`status`, and
retries up to `max_attempts`. Queue primitive: `src/services/jobs.py`.

### Registered handlers (`get_handler`)

| Job type                               | Handler                                       | Notes                                                                                                                                                                                                                                                                                                                      |
| -------------------------------------- | --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `contracts.sync`                       | `handle_contracts_sync`                       | Qualify + cache contract metadata                                                                                                                                                                                                                                                                                          |
| `contracts.chain_sync`                 | `handle_contracts_chain_sync`                 | IND → FUT → option chain catalog                                                                                                                                                                                                                                                                                           |
| `contracts.qualify_and_snapshot`       | `handle_contracts_qualify_and_snapshot`       | On-demand single-contract qualify + price                                                                                                                                                                                                                                                                                  |
| `order.fetch_sync`                     | `handle_order_fetch_sync`                     | Pull broker order state (read-only)                                                                                                                                                                                                                                                                                        |
| `watchlist.add_instrument`             | `handle_watchlist_add_instrument`             | Resolve/qualify + add to watch list                                                                                                                                                                                                                                                                                        |
| `watchlist.quotes_refresh`             | `handle_watchlist_quotes_refresh`             | Refresh live quotes for watch lists                                                                                                                                                                                                                                                                                        |
| `trades.sync.flexquery`                | `handle_trades_sync_flexquery`                | Trade sync entrypoint — fans out to one `initiate_request` per active token ([trades-and-executions-sync.md](trades-and-executions-sync.md))                                                                                                                                                                               |
| `trades.flexquery.initiate_request`    | `handle_trades_flexquery_initiate_request`    | Phase 1: ask IBKR for the statement, schedule the collection                                                                                                                                                                                                                                                               |
| `trades.flexquery.fetch_report`        | `handle_trades_flexquery_fetch_report`        | Phase 2: collect the statement and sync trades                                                                                                                                                                                                                                                                             |
| `positions.sync.flexquery`             | `handle_positions_sync_flexquery`             | Position sync entrypoint — same fan-out, default window is one day                                                                                                                                                                                                                                                         |
| `positions.flexquery.initiate_request` | `handle_positions_flexquery_initiate_request` | Phase 1 for positions                                                                                                                                                                                                                                                                                                      |
| `positions.flexquery.fetch_report`     | `handle_positions_flexquery_fetch_report`     | Phase 2 for positions                                                                                                                                                                                                                                                                                                      |
| `market_data.futures_prices`           | `handle_market_data_futures_prices`           | See [security-data.md](security-data.md)                                                                                                                                                                                                                                                                                   |
| `market_data.futures_options`          | `handle_market_data_futures_options`          | See [security-data.md](security-data.md)                                                                                                                                                                                                                                                                                   |
| `market_data.snapshot`                 | `handle_market_data_snapshot`                 | Targeted price snapshot                                                                                                                                                                                                                                                                                                    |
| `intraday.sync.tws`                    | `handle_intraday_sync_tws`                    | Live intraday overlay: `ib.positions()` + marks + today's fills → `live_positions`/`latest_quote`/`live_executions` (read-time merge in the TradeGroup view). Requires a TWS/Gateway session during market hours; if unavailable, the overlay simply shows no live data and the view degrades to settled FlexQuery values. |
| `contracts.sync_activated`             | `handle_contracts_sync_activated`             | Discover exchange/metadata + sync next-12-calendar-month FUT contracts for each row in `activated_products`. See [activated products plan](../plans/2026-06-20-001-feat-activated-products-security-master-plan.md).                                                                                                       |
| `option_metrics.sync.tws`              | `handle_option_metrics_sync_tws`              | Live option metrics overlay. See [option-metrics-overlay.md](option-metrics-overlay.md).                                                                                                                                                                                                                                   |

### TWS client IDs

TWS allows one connection per client ID, so every process that connects must
hold its own. A job's `client_id` payload field overrides its default.

| Client ID | Holder                                                                                                                        |
| --------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 0         | `worker:order-stream` (`ORDER_STREAM_CLIENT_ID`, default 0; hand-entered orders report client 0)                              |
| 30        | `worker:orders` (order submission)                                                                                            |
| 31        | `positions.sync.tws`                                                                                                          |
| 32        | `contracts.sync`, `contracts.chain_sync`                                                                                      |
| 33        | `trades.sync.tws`                                                                                                             |
| 34        | `watchlist.add_instrument`                                                                                                    |
| 35-41     | `market_data.*`, `contracts.qualify_and_snapshot`, `contracts.sync_activated`, `intraday.sync.tws`, `option_metrics.sync.tws` |
| 42        | `order.fetch_sync`                                                                                                            |
| 141       | `watchlist.quotes_refresh` (`BROKER_TWS_QUOTES_CLIENT_ID`)                                                                    |

`order.fetch_sync` does not need client 0: `reqAllOpenOrders` returns orders
entered by hand in TWS on any client ID. After each sync the worker POSTs
`/events/notify-order` per created or updated order, so open browsers update
without a refresh.

### Defined but NOT registered (dormant)

The TWS sync handlers exist but are intentionally absent from the dispatch table
while FlexQuery is the active path. Re-enable by adding them to `get_handler`:

- `positions.sync.tws` → `handle_positions_sync_tws`
- `trades.sync.tws` → `handle_trades_sync_tws`

Job-type constants live in `src/services/jobs.py`. The
`20260513080943_rename_job_type_tws_flexquery` migration backfilled the old
`positions.sync` / `trades.sync` strings to the new `.tws` / `.flexquery` forms.

## Orders worker (`worker:orders`)

> **Order submission is currently disabled.** `process_order` in
> `src/services/order_worker.py` raises `RuntimeError("Order execution is not supported at this time.")` before
> the `placeOrder` call. The worker reconciles and tracks existing orders but
> never places new ones. See
> [the worker order recovery plan](../plans/2026-02-24-001-feat-worker-order-recovery-plan.md) for the plan to
> productionize this path.

What it does today:

- Queue primitive: `src/services/order_queue.py`; mutations: `src/services/order_mutations.py`.
- Worker policy (IB status normalization, contract qualification, trade progress,
  startup reconciliation): `src/services/order_worker.py`. `scripts/work_order_queue.py`
  is the loop only (env, argparse, TWS connect, claim/poll), the same split as
  `scripts/work_jobs.py` and `src/workers/jobs.py`.
- Runs startup reconciliation against TWS before claiming work, to avoid duplicate
  broker submissions after a restart.
- Polls `orders` for `queued` rows and would set a deterministic
  `orderRef=ngtrader-order-{id}` for dedup (submission blocked).
- Status lifecycle: `queued → submitting → submitted → partially_filled/filled/cancelled/rejected/failed/reconcile_required`.
- Every status write goes through `transition_order_status` in `order_queue.py`, which
  checks the transition table. Reconciliation follows the broker's reported state even
  when the table disallows the move (`force=True`); that is recorded as a
  `forced_status_change` order event naming the from/to statuses.

The Tradebot agent has **no** order-submit tool; it can only `preview_order` and
enqueue `order.fetch_sync`. See [tradebot-chatbot.md](tradebot-chatbot.md).

## Order stream (`worker:order-stream`)

Holds client 0 with `reqAutoOpenOrders(True)`, so orders entered in TWS reach
`/orders` within seconds without Sync. It writes orders only; fills stay with
`intraday.sync.tws`, which it queues on each `execDetails` (one follow-up run if
one was already running). It never places, changes, or cancels a broker order.

- **Prod only.** Set `ORDER_STREAM_ENABLED=true` in `.env.prod` only. Dev and prod
  share a TWS port, and one process may hold the push ID. A refused ID is retried
  after a back-off; no other ID is tried.
- **Run:** `task worker:order-stream` (exits at once if the flag is unset).
- **Reconnect:** after any disconnect it fetches the full book, sweeps orders TWS
  no longer shows to `reconcile_required` (only if every fetch succeeded), and then
  applies events queued meanwhile.
- **Health:** heartbeat `order_stream`; `details` is JSON with `state` and
  `last_event_at`. The polled `order.fetch_sync` stays the fallback.

## Heartbeats and health

- Heartbeats are stored in `worker_heartbeats`; helper `src/services/worker_heartbeat.py`.
- Status endpoint: `GET /api/v1/workers/status`.
- The UI header maps heartbeat freshness to green/yellow/red lights.
- Workers publish SSE events after committing; see [core/api-ux-sse.md](api-ux-sse.md).

## Key files

- `scripts/work_jobs.py`, `src/workers/jobs.py`, `src/services/jobs.py`
- `scripts/work_order_stream.py`, `src/services/order_stream_tws.py`
- `scripts/work_order_queue.py`, `src/services/order_worker.py`, `src/services/order_queue.py`, `src/services/order_mutations.py`
- `src/services/worker_heartbeat.py`, `src/api/routers/workers.py`
- Sync services: `src/services/{trade,position}_sync_flexquery.py`,
  `src/services/contract_sync.py`, `src/services/watchlist_quotes.py`,
  `src/services/market_data.py`
