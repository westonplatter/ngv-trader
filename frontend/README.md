# ngv-trader frontend

React + TypeScript + Vite UI for ngv-trader.

Conventions (layout, data access, state, tests) are in
[docs/contributing/frontend-style.md](../docs/contributing/frontend-style.md).

## Stack

- React 19 + React Router 7
- TypeScript 6
- Tailwind CSS 4
- Bun (package manager and test runner)
- Vite 8

## Pages

| Route | Component | Purpose |
|-------|-----------|---------|
| `/tradebot` | `TradebotChat` | AI chat interface with jobs and orders side panels |
| `/accounts` | `FlexQueryTokensTable` + `AccountsTable` | FlexQuery tokens and IBKR account aliases |
| `/positions` | `PositionsTable` | Current portfolio positions with live overlay |
| `/orders` | `OrdersTable` | Order tracking |
| `/trades` | `TradesTable` | Trade history and executions |
| `/strategies` | `StrategiesPage` | Strategies and trade groups workspace |
| `/strategies/table` | `StrategyPnlTable` | Strategy P&L table across trade groups |
| `/tags` | `TagsPage` | Free-form tags and tag search |
| `/tasks` | `TasksPage` | Task list linked to trades, positions, and groups |
| `/watchlists` | `WatchListsPage` | Instrument watch lists with live quotes |
| `/market-data` | `MarketDataPage` | Futures and options market data jobs |
| `/structures` | `PricingPage` | Options structure builder and PnL calculator |

`/` redirects to `/tradebot`. Nav entries live in `src/navItems.ts`.

## Dev

```bash
bun install
bun run dev     # port 5173
```

Or from the repo root: `task frontend`.

Append `?demo=1` to any route to render static fixtures with no backend.

## Checks

```bash
bun run typecheck && bun run lint && bun test && bun run build
```

## API

Consumes `/api/v1/*` on the FastAPI backend (default port 8000). See `src/config.ts` for base URL config.
