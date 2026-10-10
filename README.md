# Next Gen Vol (NGV) Trader

`ngv-trader` is a (Python backend + Typscript frontend) supporting traders/PMs managing strategies across multiple IBKR accounts.

## Features

- **Trades** — Sync trade fills from IBKR via FlexQuery and live TWS, review trade history

- **Positions & live P&L** — Track positions across accounts with unrealized P&L, plus a live intraday TWS overlay for current-state marks.

- **Stragies** — Organized trades and executions into strategies and trade groups, with spread-aware, per-account realized/unrealized P&L rolled up per group.

![Trades page showing executions with their trade-group tags, sync controls, and a contract-scoped filter](docs/screenshots/trades-trade-group-detail-link.png)

## Getting Started

New to the project? Follow the [Getting Started guide](docs/getting-started.md) for a full walkthrough covering prerequisites, database setup, IBKR configuration, and running the app.

## License

This project offers two license options:

- **Personal Use (free):** for an individual managing less than $1 million USD in AUM.
- **Commercial (super reasonable):** for everything else — reach out to sales@nextgenvol.com.

See [LICENSE](./LICENSE) for full terms.
