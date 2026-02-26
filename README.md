# Next Gen Trader Pro

Before using this project, read the [Disclaimer](#disclaimer).

## Dev Env Setup

Set up your local development environment using [docs/install-python-and-frontend.md](docs/install-python-and-frontend.md).

## Goals

1. Review the market's price action, levels, and behaviors with LLMs.
2. Monitor a portfolio full of different strategies and risk assets.
3. Use AI to support trading decisions and operations.

## Ideal Workflow

1. Start the IBKR TWS or IBKR API Gateway
2. Boot up the Workers, pull current positions, store them in the DB
3. Boot up the API + UI, view the current portfolio
4. Compare current positions and risk levels to strategies + groupings
5. Plan portfolio adjustments to get to desired levels
6. Submit orders via the Orders UI or Tradebot chat

## Order Execution

Orders can be submitted through two paths — both use the same idempotent create and DB lifecycle.

- **Orders API / UI** — `POST /api/v1/orders` creates a queued order; the UI provides submit and cancel controls.
- **Tradebot chat** — `preview_order` validates inputs, `submit_order` queues the order.

The `worker:orders` process polls for queued orders and submits them to TWS/Gateway. It runs startup reconciliation to prevent duplicate broker submissions after restart. After processing, it auto-enqueues broker order sync and positions sync.

Broker order sync (`order.fetch_sync`) is handled by `worker:jobs` and reconciles open/recent broker orders back into the local DB.

See [docs/tradebot-workers.md](docs/tradebot-workers.md) for worker details and [docs/spec-restore-order-fetching-and-submission.md](docs/spec-restore-order-fetching-and-submission.md) for the full implementation spec.

## Brokers

I'm planning to use this for my actual trading operations, so:

- [ ] Interactive Brokers (primary)
- [ ] Alpaca (secondary)

## Disclaimer

**This software connects to real brokerage systems and market data with real financial risk.** It is provided "as is" with no warranties of any kind.

- Read and understand the code before you run it. You are fully responsible for what it does in your account.
- The author(s) are not liable for any financial losses resulting from this software.
- This is not financial advice. Past performance is not indicative of future results.

**You assume all risk.**

## Code Gen Strategy

I like to break up code into different categories: **Primitives, Components, Services**.

### Primitives

Primitives are small discrete, functions focused on a a specific task,

- 20 lines or less (ideal goal)
- 4 or less input arguments
- exist as instance methods or stateless functions
- are focused on a specific task
- can be easily tested in isolation (eg, unit tests, but not integration tests)
- behave as mechanical operators

Examples:

- calc the opening range breakout
- df helper function

## Interfaces/Abstract Classes

### Components

Components are collections of Primitives that evolved to manage a process from start to finish.
They're often classes and keep track of "state", but I can still test 90% of what's important with unit tests.

### Services

Services are the harness for creating long-running processes that are healthy and operate well.
