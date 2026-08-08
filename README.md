# Next Gen Vol (NGV) Trader

`ngv-trader` is a (Python backend + Typscript frontend) supporting traders/PMs managing strategies across multiple IBKR accounts.

## Features

- **Trades** — Sync trade fills from IBKR via FlexQuery and live TWS, review trade history

- **Positions & live P&L** — Track positions across accounts with unrealized P&L, plus a live intraday TWS overlay for current-state marks.

- **Trade tagging & trade groups** — Organize executions into strategies and trade groups, with spread-aware, per-account realized/unrealized P&L rolled up per group.

## Getting Started

New to the project? Follow the [Getting Started guide](docs/getting-started.md) for a full walkthrough covering prerequisites, database setup, IBKR configuration, and running the app.

**You assume all risk.**

## Tests

```bash
task test
```

Runs the pytest suite against a dedicated `ngv_trader_test` database, created and migrated on demand — dev and prod data are never touched.

## Screenshots

### Positions

Track unrealized PnL across accounts, with positions grouped into trades.

![Positions](docs/screenshots/positions-demo.png)

### Strategies

Organize executions into strategies and trade groups, with realized/unrealized
PnL rolled up per group.

![Strategies](docs/screenshots/tagging-demo.png)

### Assigning Positions to Trade Groups

Assign individual positions to trade groups directly from the Positions page.

![Assign positions to trade groups](docs/screenshots/positions-trade-group-assign.png)

## License

This project offers two license options:

- **Personal Use (free):** for an individual managing less than $1 million USD in AUM.
- **Commercial (super reasonable):** for everything else — reach out to sales@nextgenvol.com.

See [LICENSE](./LICENSE) for full terms.
