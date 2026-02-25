# Tradebot LangGraph Implementation

## Summary

Tradebot chat uses an LLM-driven LangGraph workflow with explicit function tools.
As of February 23, 2026, order execution tools were removed.

Tradebot now:

- uses conversation history (not only last message)
- uses tool calls for DB reads and operational actions
- enqueues non-execution jobs through `worker:jobs`
- keeps order-related access read-only

## What Was Built

### Backend

- Added LangGraph agent service: `src/services/tradebot_agent.py`
- Replaced regex chat router with thin adapter: `src/api/routers/tradebot.py`
- Added string env helper for typed config loading: `src/utils/env_vars.py`
- Added dependency: `langgraph` in `pyproject.toml`

### Frontend

- Updated chat transport to send full message history:
  - `frontend/src/components/TradebotChat.tsx`
- Preserved current endpoint contract (`POST /api/v1/tradebot/chat`, plain text response)

### Configuration

- Added LLM env examples in `.env.example`:
  - `TRADEBOT_LLM_API_KEY` (or `OPENAI_API_KEY`)
  - `TRADEBOT_LLM_MODEL`
  - `TRADEBOT_LLM_BASE_URL`
  - `TRADEBOT_LLM_TIMEOUT_SECONDS`

## LangGraph Workflow

State graph:

- `model` node: calls OpenAI-compatible `chat/completions`
- `tools` node: executes requested function tools
- conditional edge:
  - if tool calls exist -> loop to `tools`
  - if final assistant response -> end
  - if max tool steps reached -> return tool-step-limit response

Runtime constraints:

- max chat history sent to model: 16 messages
- max tool loop iterations: 8

## Tool Surface

| Function                       | Description                                                 | Any Guardrails                                                                            |
| ------------------------------ | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `list_accounts`                | Lists available brokerage accounts for routing.             | Read-only DB query.                                                                       |
| `list_positions`               | Returns current positions from the database.                | Read-only DB query. Optional `limit` constrained to 1-200.                                |
| `list_jobs`                    | Returns recent job queue records.                           | Read-only DB query. `limit` constrained to 1-200.                                         |
| `list_orders`                  | Returns recent orders and optional recent events per order. | Read-only DB query. `limit` constrained to 1-200; `events_per_order` constrained to 1-20. |
| `lookup_contract`              | Returns contract info from DB cache.                        | Read-only DB query; no broker side effects.                                               |
| `enqueue_positions_sync_job`   | Enqueues a `positions.sync` job for `worker:jobs`.          | Writes to `jobs` queue only. `max_attempts` constrained to 1-10.                          |
| `enqueue_contracts_sync_job`   | Enqueues a `contracts.sync` job for `worker:jobs`.          | Writes to `jobs` queue only; symbol/sec_type validated before enqueue.                    |
| `list_watch_lists`             | Lists watch lists and counts.                               | Read-only DB query.                                                                       |
| `create_watch_list`            | Creates a watch list.                                       | Writes local DB only.                                                                     |
| `get_watch_list`               | Reads one watch list and instruments.                       | Read-only DB query.                                                                       |
| `add_watch_list_instrument`    | Enqueues instrument add for watch list.                     | Queues `watchlist.add_instrument` job; worker resolves/qualifies contract.                |
| `remove_watch_list_instrument` | Removes one watch list instrument.                          | Writes local DB only.                                                                     |

## Safety and Side Effects

- Execution-capable tools (`preview_order`, `check_pretrade_job`, `submit_order`) are removed.
- The system prompt explicitly tells the model that order execution is disabled.
- Job tools enqueue non-execution jobs (`positions.sync`, `contracts.sync`, `watchlist.add_instrument`).
- Tool failures are returned to the LLM as structured tool error payloads.
- DB session rolls back on tool exceptions.

## Operational Notes

- IBKR connectivity is still required for sync jobs handled by `worker:jobs`.
- `orders` and `order_events` tables remain for historical read-only visibility.
- Existing jobs/orders UI side panels still read the same API surfaces.

## Validation

Static checks run during implementation:

- Ruff: passed
- Pyright: passed
