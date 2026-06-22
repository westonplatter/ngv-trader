# Workers

Background processes that run separately from the API and consume DB-backed
queues. Two workers exist.

| Worker | Entrypoint | Queue | Status |
| --- | --- | --- | --- |
| `worker:jobs` | `scripts/work_jobs.py` | `jobs` table | Active |
| `worker:orders` | `scripts/work_order_queue.py` | `orders` table | Scaffold only — **submission is disabled** |

Start commands:

```bash
task worker:jobs
task worker:orders
```

Pass `ENV=prod` to target production: `ENV=prod task worker:jobs`.

## Jobs worker (`worker:jobs`)

The job logic lives in `src/workers/jobs.py` (handlers, the `get_handler`
dispatch table, and a shared `IBSessionPool`). `scripts/work_jobs.py` is a thin
CLI shim that claims queued jobs, runs the handler, writes `result`/`status`, and
retries up to `max_attempts`. Queue primitive: `src/services/jobs.py`.

### Registered handlers (`get_handler`)

| Job type | Handler | Notes |
| --- | --- | --- |
| `contracts.sync` | `handle_contracts_sync` | Qualify + cache contract metadata |
| `contracts.chain_sync` | `handle_contracts_chain_sync` | IND → FUT → option chain catalog |
| `contracts.qualify_and_snapshot` | `handle_contracts_qualify_and_snapshot` | On-demand single-contract qualify + price |
| `order.fetch_sync` | `handle_order_fetch_sync` | Pull broker order state (read-only) |
| `watchlist.add_instrument` | `handle_watchlist_add_instrument` | Resolve/qualify + add to watch list |
| `watchlist.quotes_refresh` | `handle_watchlist_quotes_refresh` | Refresh live quotes for watch lists |
| `trades.sync.flexquery` | `handle_trades_sync_flexquery` | Primary trade sync ([trades-and-executions-sync.md](trades-and-executions-sync.md)) |
| `positions.sync.flexquery` | `handle_positions_sync_flexquery` | Primary position sync |
| `market_data.futures_prices` | `handle_market_data_futures_prices` | See [security-data.md](security-data.md) |
| `market_data.futures_options` | `handle_market_data_futures_options` | See [security-data.md](security-data.md) |
| `market_data.snapshot` | `handle_market_data_snapshot` | Targeted price snapshot |
| `contracts.sync_activated` | `handle_contracts_sync_activated` | Discover exchange + sync 12-month FUT window for activated products |

### Defined but NOT registered (dormant)

The TWS sync handlers exist but are intentionally absent from the dispatch table
while FlexQuery is the active path. Re-enable by adding them to `get_handler`:

- `positions.sync.tws` → `handle_positions_sync_tws`
- `trades.sync.tws` → `handle_trades_sync_tws`

Job-type constants live in `src/services/jobs.py`. The
`20260513080943_rename_job_type_tws_flexquery` migration backfilled the old
`positions.sync` / `trades.sync` strings to the new `.tws` / `.flexquery` forms.

## Orders worker (`worker:orders`)

> **Order submission is currently disabled.** `scripts/work_order_queue.py`
> raises `RuntimeError("Order execution is not supported at this time.")` before
> the `placeOrder` call. The worker reconciles and tracks existing orders but
> never places new ones. See
> [spec-worker-order-recovery.md](spec-worker-order-recovery.md) for the plan to
> productionize this path.

What it does today:

- Queue primitive: `src/services/order_queue.py`; mutations: `src/services/order_mutations.py`.
- Runs startup reconciliation against TWS before claiming work, to avoid duplicate
  broker submissions after a restart.
- Polls `orders` for `queued` rows and would set a deterministic
  `orderRef=ngtrader-order-{id}` for dedup (submission blocked).
- Status lifecycle: `queued → submitting → submitted → partially_filled/filled/rejected/failed`.

The Tradebot agent has **no** order-submit tool; it can only `preview_order` and
enqueue `order.fetch_sync`. See [tradebot-chatbot.md](tradebot-chatbot.md).

## Heartbeats and health

- Heartbeats are stored in `worker_heartbeats`; helper `src/services/worker_heartbeat.py`.
- Status endpoint: `GET /api/v1/workers/status`.
- The UI header maps heartbeat freshness to green/yellow/red lights.
- Workers publish SSE events after committing; see [core/api-ux-sse.md](core/api-ux-sse.md).

## Key files

- `scripts/work_jobs.py`, `src/workers/jobs.py`, `src/services/jobs.py`
- `scripts/work_order_queue.py`, `src/services/order_queue.py`, `src/services/order_mutations.py`
- `src/services/worker_heartbeat.py`, `src/api/routers/workers.py`
- Sync services: `src/services/{trade,position}_sync_flexquery.py`,
  `src/services/contract_sync.py`, `src/services/watchlist_quotes.py`,
  `src/services/market_data.py`
