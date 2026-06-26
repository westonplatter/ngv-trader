# Docs Index

Documentation for ngv-trader. **Current-state** docs describe how the system
works today; **specs** describe proposed/in-progress work and carry a status
banner at the top.

## Start here

| Doc                                                      | What it covers                                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| [getting-started.md](getting-started.md)                 | End-to-end local setup: prerequisites, env, Postgres, IBKR/TWS, running the app and workers |
| [secrets-using-1password.md](secrets-using-1password.md) | Resolving `op://` secret references in `.env.*` via the 1Password CLI                       |

## Architecture & subsystems (current state)

| Doc                                                                  | What it covers                                                                                                          |
| -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| [workers.md](workers.md)                                             | `worker:jobs` handler map and `worker:orders` (submission disabled); heartbeats and health                              |
| [trades-and-executions-sync.md](trades-and-executions-sync.md)       | Trade/position ingestion via FlexQuery (TWS dormant), spread/combo detection, corrections, idempotency, `flex_sync_log` |
| [security-data.md](security-data.md)                                 | Market-data tables (`latest_*` / `ts_*`), futures/options fetch jobs, and futures read API                              |
| [contract-ref-setup.md](contract-ref-setup.md)                       | `contracts` (SecRef) cache, `contracts.sync`, and the agent↔IBKR boundary                                               |
| [contract-display-names.md](contract-display-names.md)               | How human-readable contract labels are built across positions/orders/trades/watchlists                                  |
| [trade-tagging.md](trade-tagging.md)                                 | Trade groups, tag catalogs, execution assignment, timeline, and tagging UI                                              |
| [tradebot-chatbot.md](tradebot-chatbot.md)                           | LangGraph chat agent: tools, guardrails, env vars (no order submission)                                                 |
| [osi-semantic-layer.md](osi-semantic-layer.md)                       | OSI semantic model + `query_metric` tool: tradebot analytics (realized PnL / win rate) as read-only SQL by metric name  |
| [user-preferences-privacy-mode.md](user-preferences-privacy-mode.md) | Key-value user preferences and frontend privacy masking                                                                 |

## Core UX & platform patterns

| Doc                                                          | What it covers                                                                                                                                            |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [core/intraday-tws-overlay.md](core/intraday-tws-overlay.md) | Optional live current-state P&L overlay from TWS (`live_positions`/`latest_quote`/`live_executions`), read-time merge over the settled FlexQuery snapshot |
| [core/api-ux-sse.md](core/api-ux-sse.md)                     | Real-time UI via Server-Sent Events: broadcaster, notify endpoints, event envelope                                                                      |
| [core/ux-actions.md](core/ux-actions.md)                     | Reusable action patterns: destructive confirmation, save feedback, state model                                                                          |
| [core/ux-pricing.md](core/ux-pricing.md)                     | Pricing page: two-tier contract catalog, on-demand qualification, expected-PnL flow                                                                     |

## Planning & process

| Doc                                                    | What it covers                                                     |
| ------------------------------------------------------ | ----------------------------------------------------------------- |
| [db-snapshots.md](db-snapshots.md)                     | Postgres snapshot/verify/restore before hard-to-reverse DB changes |
| [planning-spec-format.md](planning-spec-format.md)     | Template and conventions for writing a new `spec-*.md`            |
| [planning-agents-quorum.md](planning-agents-quorum.md) | Agent quorum roles used to shape trade-tagging requirements       |
| [doc-review.md](doc-review.md)                         | Checklist and conventions for reviewing and refining project docs |

## Open specs (proposed / in progress)

Each carries a status banner; none is fully shipped.

| Spec                                                                                         | Status                                                                             |
| -------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| [spec-first-class-realized-pnl-on-trades.md](spec-first-class-realized-pnl-on-trades.md)     | Not implemented — PnL computed on read from `raw`                                  |
| [spec-tradebot-contract-metadata-autofetch.md](spec-tradebot-contract-metadata-autofetch.md) | Partial — on-demand fetch works; order-flow + background freshness pending         |
| [spec-worker-order-recovery.md](spec-worker-order-recovery.md)                               | Partial scaffold — submission disabled; crash-safety fields pending                |
| [spec-activated-products-security-master.md](spec-activated-products-security-master.md)     | Proposed — activated-products table, IBKR exchange discovery, 12-month sync        |
| [spec-auto-tag-suggestions.md](spec-auto-tag-suggestions.md)                                 | Proposed — human-reviewed tag/assignment suggestions for closing and rolling fills |
