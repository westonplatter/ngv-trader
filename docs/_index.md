# Docs Index

## Project Docs

| File                                                                         | Tags                                                           | Description                                                                                                     |
| ---------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| [contract-ref-setup.md](contract-ref-setup.md)                               | ibkr, contracts, secref, jobs, watchlist, architecture         | Contract reference (SecRef) setup for IB contract caching, sync jobs, and agent-safe contract lookup            |
| [download-positions.md](download-positions.md)                               | ibkr, postgres, positions, db                                  | Download IBKR positions from TWS and store in Postgres                                                          |
| [secrets-using-1password.md](secrets-using-1password.md)                     | secrets, 1password, env                                        | Using 1Password CLI to manage secrets in `.env.dev` and `.env.prod` files                                       |
| [tradebot-chatbot.md](tradebot-chatbot.md)                                   | tradebot, chatbot, langgraph, llm, tools, api, ui, safety      | LangGraph chat architecture, read/ops tool surface, safety constraints, env vars, and UI components             |
| [tradebot-langgraph-implementation.md](tradebot-langgraph-implementation.md) | tradebot, langgraph, llm, tools, implementation, api, frontend | LangGraph implementation notes including the current non-execution tool surface and guardrails                  |
| [tradebot-workers.md](tradebot-workers.md)                                   | workers, jobs, heartbeat, watchlist, architecture              | Worker construction details for `worker:jobs`, including watchlist quotes refresh handlers and heartbeat health |

## Specs

| File                                                                               | Tags                                                  | Description                                                                                                             |
| ---------------------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| [spec-client-portal-combo-spreads.md](spec-client-portal-combo-spreads.md)         | ibkr, cpapi, spreads, cl, positions, architecture     | Spec for adding IBKR Client Portal combo-position sync and a native CL time-spread view                                 |
| [spec-installable-internal-app-layout.md](spec-installable-internal-app-layout.md) | architecture, uv, packaging, src-layout               | Spec for migrating from `src` imports to an installable internal package at `src/ngtrader`                              |
| [spec-mastra-chat-service-split.md](spec-mastra-chat-service-split.md)             | architecture, mastra, fastapi, chat, tools, safety    | Spec for splitting chat orchestration into Mastra while keeping FastAPI as system-of-record for orders and data         |
| [spec-remove-order-execution.md](spec-remove-order-execution.md)                   | orders, execution, safety, decommission, architecture | Decommission spec with phased status for removing order submission paths while preserving read-only order history       |
| [spec-trades-and-executions-sync.md](spec-trades-and-executions-sync.md)           | ibkr, trades, executions, sync, worker, api, postgres | Spec for ingesting IBKR trades with execution-level source-of-truth, correction handling, and idempotent sync semantics |
| [spec-worker-order-recovery.md](spec-worker-order-recovery.md)                     | orders, worker, recovery, tws, failover               | Spec for reboot-safe order worker lifecycle and recovery with a 42-step implementation plan                             |
