# Next Gen Trader

Before using this project, read the [Disclaimer](#disclaimer).

## Goals

1. Review the market's price action, levels, and behaviors with LLMs.
2. Monitor a portfolio full of different strategies and risk assets.
3. Use AI to support trading decisions and operations.

## Ideal Workflow

1. Start the IBKR TWS or IBKR API Gateway
2. Boot up the Worker, pull current positions, store them in the DB
3. Boot up the API + UI, view the current portfolio
4. Compare current positions and risk levels to strategies + groupings
5. Plan portfolio adjustments to get to desired levels

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

Primitives are small discrete functions that are 20 lines or less.
They're focused on a specific task and can be easily unit tested.
I like to keep "state" out of these functions.
These are mechanical operators.

Examples:

- function to calc the opening range breakout

### Components

Components are collections of Primitives that evolved to manage a process from start to finish.
They're often classes and keep track of "state", but I can still test 90% of what's important with unit tests.

### Services

Services are the harness for creating long-running processes that are healthy and operate well.
