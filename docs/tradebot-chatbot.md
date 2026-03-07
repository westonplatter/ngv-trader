# Tradebot Chatbot

## Purpose

`/api/v1/tradebot/chat` is the operator chat control surface.

It runs as an LLM conversation workflow with LangGraph and explicit function tools.
Order execution is enabled through controlled tools.

## Architecture

- Frontend uses Vercel AI SDK `useChat` with `TextStreamChatTransport`.
- Client sends chat history (`messages[]`) to preserve conversation context.
- FastAPI router (`src/api/routers/tradebot.py`) normalizes chat messages and calls the agent service.
- Agent service (`src/services/tradebot_agent.py`) runs a LangGraph state machine:
  - `model` node: calls an OpenAI-compatible `chat/completions` model
  - `tools` node: executes requested tool calls against DB/workflows
  - conditional routing loops until final assistant response or tool-step limit

## Available Tools

Read tools:

- `list_accounts`
- `list_positions`
- `list_jobs`
- `list_orders`
- `lookup_contract` — checks DB first, falls back to IBKR fetch if not found. Supports `contract_expiry` (YYYY-MM-DD) for specific weekly option expiries.
- `list_watch_lists`
- `get_watch_list`

Action tools:

- `preview_order`
- `submit_order`
- `enqueue_positions_sync_job`
- `enqueue_contracts_sync_job`
- `enqueue_order_fetch_sync_job`
- `create_watch_list`
- `add_watch_list_instrument`
- `remove_watch_list_instrument`

## Safety Constraints

- Tradebot can validate (`preview_order`) and queue (`submit_order`) orders.
- Tradebot does not have an order-cancel tool; use Orders API/UI cancel path.
- Side-effect jobs are limited to `worker:jobs` handlers.
- If an action tool fails, the tool call returns an explicit error payload back to the model.

## Environment Variables

- `TRADEBOT_LLM_API_KEY` (or fallback `OPENAI_API_KEY`)
- `TRADEBOT_LLM_MODEL` (default `gpt-5-mini`)
- `TRADEBOT_LLM_BASE_URL` (default `https://api.openai.com/v1`)
- `TRADEBOT_LLM_TIMEOUT_SECONDS` (default `45`)
- `BROKER_TWS_PORT` (required for jobs that connect to IBKR: positions/contracts/watchlist instrument fetch)
- `BROKER_CL_MIN_DAYS_TO_EXPIRY` (default `7`; skip CL contracts too close to expiry)

## UI Components

- `TradebotChat` main chat panel
- `JobsTable` side panel (job timing + actions)
- `OrdersSideTable` side panel (order timing + status/fill)
- Header worker lights from `/api/v1/workers/status`

## Key Files

- `src/api/routers/tradebot.py`
- `src/services/tradebot_agent.py`
- `frontend/src/components/TradebotChat.tsx`
- `frontend/src/components/JobsTable.tsx`
- `frontend/src/components/OrdersSideTable.tsx`
