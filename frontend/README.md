# ngv-trader frontend

React + TypeScript + Vite UI for ngv-trader.

## Stack

- React 19 + React Router 7
- TypeScript 5
- Tailwind CSS 4
- Bun (package manager)
- Vite 7

## Pages

| Route | Component | Purpose |
|-------|-----------|---------|
| `/tradebot` | `TradebotChat` | AI chat interface |
| `/accounts` | `AccountsTable` | IBKR account management |
| `/positions` | `PositionsTable` | Current portfolio positions |
| `/orders` | `OrdersTable` | Order tracking |
| `/trades` | `TradesTable` | Trade history and executions |
| `/tagging` | `TradeTaggingPage` | Trade group and strategy tagging |
| `/watchlists` | `WatchListsPage` | Instrument watch lists with live quotes |
| `/market-data` | `MarketDataPage` | Futures and options market data |
| `/structures` | `PricingPage` | Options structure builder and PnL calculator |

## Dev

```bash
bun install
bun run dev     # port 5173
```

Or from the repo root: `task frontend`.

## API

Consumes `/api/v1/*` on the FastAPI backend (default port 8000). See `src/config.ts` for base URL config.
