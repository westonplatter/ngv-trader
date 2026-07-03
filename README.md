# Next Gen Vol (NGV) Trader

Agentic trading software that lets one person run a nimble, quantitative
futures, volatility, and options desk. NGV Trader connects to Interactive
Brokers (TWS / IB Gateway), keeps your positions and trades in sync, and rolls
everything up into strategy-level P&L — with a natural-language assistant on top.

## Features

- **Positions & live P&L** — Track positions across accounts with unrealized
  P&L, plus a live intraday TWS overlay for current-state marks.
- **Trade tagging & trade groups** — Organize executions into strategies and
  trade groups, with spread-aware, per-account realized/unrealized P&L rolled
  up per group.
- **Trades & orders** — Sync fills from IBKR via FlexQuery and live TWS, review
  trade history, and manage working orders.
- **Watch lists** — Curate contracts and instruments you want to keep an eye on.
- **Market data** — Enqueue and monitor market-data jobs, with live updates
  streamed to the UI.
- **Structures & pricing** — Build and price multi-leg options and futures
  structures.
- **Tradebot** — A natural-language assistant to query positions, contracts,
  watch lists, and jobs in plain English.

## Getting Started

New to the project? Follow the [Getting Started guide](docs/getting-started.md) for a full walkthrough covering prerequisites, database setup, IBKR configuration, and running the app.

**You assume all risk.**

## Screenshots

### Positions
Track unrealized PnL across accounts, with positions grouped into trades.

![Positions](docs/screenshots/positions-demo.png)

### Trade Tagging
Organize executions into strategies and trade groups, with realized/unrealized
PnL rolled up per group.

![Trade Tagging](docs/screenshots/tagging-demo.png)

### Assigning Positions to Trade Groups
Assign individual positions to trade groups directly from the Positions page.

![Assign positions to trade groups](docs/screenshots/positions-trade-group-assign.png)

## License

This project offers two license options:

- **Personal Use (free):** for an individual managing less than $1 million USD in AUM.
- **Commercial (super reasonable):** for everything else — reach out to sales@nextgenvol.com.

See [LICENSE](./LICENSE) for full terms.
