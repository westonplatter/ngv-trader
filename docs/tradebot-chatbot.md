# Tradebot Chatbot

## Purpose

`/api/v1/tradebot/chat` is the operator chat control surface — an LLM
conversation that reads portfolio data and triggers background work through
explicit function tools.

> **Tradebot cannot place orders.** It can `preview_order` (validate/normalize)
> but there is no `submit_order` tool, and the orders worker has submission
> disabled. See [workers.md](workers.md).

## Architecture

- Frontend uses Vercel AI SDK `useChat` with `TextStreamChatTransport`; it sends
  the full `messages[]` history to preserve context.
- FastAPI router (`src/api/routers/tradebot.py`) normalizes messages and calls
  the agent service.
- Agent service (`src/services/tradebot_agent.py`) runs a LangGraph state machine:
  - `model` node — calls an OpenAI-compatible `chat/completions` model
  - `tools` node — executes requested tool calls against the DB / job queue
  - conditional edge loops until a final assistant message or the tool-step limit
- Runtime limits: max 16 history messages sent to the model; max 8 tool-loop
  iterations.

## Tools

The agent **never imports `ib_async`** — it reads from the DB and enqueues jobs;
only `worker:jobs` talks to IBKR.

Read tools:

- `list_accounts`, `list_positions`, `list_jobs`, `list_orders`
- `lookup_contract` — DB-first, falls back to an IBKR fetch on miss; supports
  `contract_expiry` (YYYY-MM-DD) for specific weekly option expiries
- `list_watch_lists`, `get_watch_list`
- `check_watchlist_job` — poll status of a queued watch-list job
- `query_metric` — run business-analyst metrics (realized PnL, win rate, trade
  count) from the OSI semantic model as read-only SQL, by metric/dimension name.
  See [core/semantic-queries.md](core/semantic-queries.md). The agent picks names only;
  it does not write SQL.
- `trade_group_pnl` — realized + settled/intraday unrealized PnL for one trade
  group (the detail-view figures), reusing the live overlay. See
  [core/semantic-queries.md](core/semantic-queries.md) §9.

Action tools:

- `preview_order` — validates/normalizes an order request; no DB writes, no submit
- `enqueue_positions_sync_job`, `enqueue_contracts_sync_job`, `enqueue_order_fetch_sync_job`
- `create_watch_list`, `add_watch_list_instrument`, `remove_watch_list_instrument`

Guardrails: list/limit params are bounded; failed tool calls return a structured
error payload to the model; the DB session rolls back on tool exceptions.

## Environment variables

- `TRADEBOT_LLM_API_KEY` (or fallback `OPENAI_API_KEY`)
- `TRADEBOT_LLM_MODEL` (default `gpt-5-mini`)
- `TRADEBOT_LLM_BASE_URL` (default `https://api.openai.com/v1`)
- `TRADEBOT_LLM_TIMEOUT_SECONDS` (default `45`)
- `BROKER_TWS_PORT` (required for `worker:jobs` IBKR connections)
- `BROKER_CL_MIN_DAYS_TO_EXPIRY` (default `7`; skip CL contracts near expiry)

## UI components

- `TradebotChat` — main chat panel
- `JobsTable` — jobs side panel (timing + actions)
- `OrdersSideTable` — orders side panel (status/fill)
- Header worker lights from `/api/v1/workers/status`

## Key files

- `src/api/routers/tradebot.py`
- `src/services/tradebot_agent.py`
- `src/services/semantic/` + `osi/ngv_semantic_model.yaml` (the `query_metric` semantic layer)
- `frontend/src/components/{TradebotChat,JobsTable,OrdersSideTable}.tsx`
