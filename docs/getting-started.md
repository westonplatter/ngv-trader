# Getting Started

A step-by-step guide to set up ngv-trader locally and start using it.

## Architecture Overview

ngv-trader has four main components that work together:

```text
┌─────────────────┐     ┌──────────────────┐     ┌──────────────┐
│  React Frontend │────▶│  FastAPI Backend │────▶│  PostgreSQL  │
│  (Vite, :5173)  │     │  (Uvicorn, :8000)│     │  (:5432)     │
└─────────────────┘     └──────────────────┘     └──────────────┘
                                                       ▲
                                                       │
                        ┌──────────────┐         ┌─────┴────────┐
                        │ IBKR TWS /   │◀────────│  Workers     │
                        │ IB Gateway   │         │  (jobs,      │
                        │ (:7497)      │         │   orders)    │
                        └──────────────┘         └──────────────┘
```

| Component              | Purpose                                                                                      |
| ---------------------- | -------------------------------------------------------------------------------------------- |
| **Frontend**           | React/TypeScript UI for viewing positions, orders, trades, watchlists, and the Tradebot chat |
| **Backend**            | FastAPI REST API serving data from Postgres and proxying LLM chat                            |
| **Workers**            | Background processes that sync data (positions, contracts, quotes) with IBKR                 |
| **PostgreSQL**         | Stores accounts, positions, orders, trades, contracts, watchlists, and jobs                  |
| **IBKR TWS / Gateway** | Interactive Brokers connection for live market data                                          |

## Prerequisites

Install these before proceeding:

| Tool                   | Version  | Install                                                                             |
| ---------------------- | -------- | ----------------------------------------------------------------------------------- | --- |
| `uv`                   | latest   | `curl -LsSf https://astral.sh/uv/install.sh                                         | sh` |
| Bun                    | 1.0+     | [bun.sh](https://bun.sh/)                                                           |
| PostgreSQL             | 14+      | [postgresql.org](https://www.postgresql.org/download/) or `brew install postgresql` |
| Task                   | latest   | [taskfile.dev](https://taskfile.dev/docs/installation)                              |
| IBKR TWS or IB Gateway | optional | [interactivebrokers.com](https://www.interactivebrokers.com/en/trading/tws.php)     |

## 1. Clone and Install Dependencies

```bash
git clone <repo-url> ngv-trader
cd ngv-trader
```

Install Python dependencies:

```bash
uv sync
```

Install frontend dependencies:

```bash
cd frontend
bun install
cd ..
```

Or use the task shortcut:

```bash
task frontend:install
```

## 2. Configure Environment Variables

Copy the example env file and fill in your values:

```bash
cp .env.example .env.dev
```

Edit `.env.dev` with your database and broker settings:

```bash
# PostgreSQL connection
DB_HOST=localhost
DB_PORT=5432
DB_NAME=ngtrader_dev
DB_USER=postgres
DB_PASSWORD=your_password

# IBKR TWS/Gateway API port (optional)
# TWS default: 7497 (paper) or 7496 (live)
# Gateway default: 4002 (paper) or 4001 (live)
BROKER_TWS_PORT=7497

# CL futures near-expiry safety window (days)
BROKER_CL_MIN_DAYS_TO_EXPIRY=7

# Tradebot LLM (optional — needed only for the chat feature)
# TRADEBOT_LLM_API_KEY=sk-...
# TRADEBOT_LLM_MODEL=gpt-4.1-mini
# TRADEBOT_LLM_BASE_URL=https://api.openai.com/v1
# TRADEBOT_LLM_TIMEOUT_SECONDS=45
```

### Secrets with 1Password (optional)

If you use 1Password, values in `.env.dev` can reference secrets with `op://` URIs instead of plain text:

```bash
DB_PASSWORD=op://MyVault/ngtrader-db/password
BROKER_TWS_PORT=op://MyVault/ibkr/tws-port
```

To resolve `op://` references, wrap any command with `op run`:

```bash
op run --env-file=.env.dev -- task api
op run --env-file=.env.dev -- uv run python scripts/setup_db.py --env dev
```

`op run` resolves the references and injects the real values as environment variables before the inner command starts. All `task` commands work with or without the `op run` wrapper — it's your choice.

See [secrets-using-1password.md](secrets-using-1password.md) for details.

If you do **not** use 1Password, just use plain values in `.env.dev` and run commands directly.

## 3. Set Up PostgreSQL

Make sure PostgreSQL is running, then create the database and run migrations:

```bash
uv run python scripts/setup_db.py --env dev
```

This script:

1. Connects to the `postgres` maintenance database
2. Creates `ngtrader_dev` (or whatever `DB_NAME` is set to) if it doesn't exist
3. Runs all Alembic migrations to bring the schema up to date

You can also run migrations independently:

```bash
task migrate
```

## 4. Validate Your Setup

Run the environment validator to confirm everything is wired up correctly:

```bash
task validate
```

This checks your `.env.dev` file, PostgreSQL connectivity, migration status, and TWS connectivity. To skip the TWS check if you don't have IBKR running:

```bash
task validate -- --no-tws
```

## 5. Set Up IBKR TWS or IB Gateway (optional)

ngv-trader connects to Interactive Brokers through TWS (Trader Workstation) or IB Gateway. You need one of them running locally for live data sync.

### Configure TWS / Gateway for API access

1. Open TWS or IB Gateway
2. Go to **Edit > Global Configuration > API > Settings**
3. Enable **"Enable ActiveX and Socket Clients"**
4. Set the **Socket port** (default 7497 for paper trading)
5. Add `127.0.0.1` to **Trusted IPs**

### Test the connection

```bash
uv run python scripts/test_tws_connection.py --env dev
```

A successful test prints the server version, managed accounts, and net liquidation value.

### Download Initial Data from IBKR

With TWS/Gateway running, pull your current positions into the database:

```bash
uv run python scripts/download_positions.py --env dev
```

This connects to IBKR, fetches all positions across your managed accounts, creates `Account` rows, and upserts positions into the `positions` table.

See [download-positions.md](download-positions.md) for details on accounts, aliases, and verification.

## 6. Start the Application

You need to start the backend and frontend. In two separate terminals:

**Terminal 1 — Backend API (port 8000):**

```bash
task api
```

The API validates the database connection on startup. If PostgreSQL is unreachable, you'll see a clear error message immediately instead of a silent failure.

**Terminal 2 — Frontend dev server (port 5173):**

```bash
task frontend
```

Or start both at once:

```bash
task dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

### Check API health

With the API running, verify everything is connected:

```bash
curl http://localhost:8000/api/v1/health
```

Returns `{"status": "ok", "database": "connected"}` when everything is working.

### Start workers (optional — needed for live sync)

Workers are background processes that sync data with IBKR. Run in its own terminal:

**Terminal 3 — Jobs worker** (position sync, contract sync, watchlist quotes):

```bash
task worker:jobs
```

Workers require TWS/Gateway to be running. The UI header shows worker health lights (green/yellow/red) based on heartbeat freshness.

See [tradebot-workers.md](tradebot-workers.md) for worker architecture details.

## 7. Using the Application

### Pages

| Page            | URL           | What it does                                              |
| --------------- | ------------- | --------------------------------------------------------- |
| **Tradebot**    | `/tradebot`   | AI chat interface — ask about positions, trigger syncs    |
| **Accounts**    | `/accounts`   | View IBKR accounts and set display aliases                |
| **Positions**   | `/positions`  | View current holdings with filters, trigger position sync |
| **Orders**      | `/orders`     | View synced orders and track fill status                  |
| **Trades**      | `/trades`     | View executed trade history and fill details              |
| **Watch Lists** | `/watchlists` | Create watchlists, add instruments, view live quotes      |

### Common workflows

**Sync positions from IBKR:**

- Click the sync button on the Positions page, or
- Ask the Tradebot: "sync my positions"

**View live quotes:**

- Create a watchlist on the Watch Lists page
- Add instruments (stocks, futures, options)
- Quotes auto-refresh while the page is open (requires `worker:jobs` running)

**Fetch contract metadata:**

- Ask the Tradebot: "what CL futures are available?"
- It will look up cached contracts or trigger a sync if needed

### Tradebot chat

The Tradebot is an LLM-powered assistant that can read your portfolio data and take actions. It requires `TRADEBOT_LLM_API_KEY` to be set in your env file.

Available commands include listing accounts/positions/orders, syncing positions and contracts, and managing watchlists. See [tradebot-chatbot.md](tradebot-chatbot.md) for the full tool list.

## Quick Reference: Task Commands

```bash
task list              # Show all available tasks
task api               # Start FastAPI backend (port 8000)
task frontend          # Start Vite frontend (port 5173)
task dev               # Start both API and frontend
task frontend:install  # bun install for frontend
task migrate           # Run Alembic migrations to head
task migrate:down      # Roll back one migration
task migrate:new -- "description"  # Create a new migration
task worker:jobs       # Start jobs worker (position sync, quotes)
task validate          # Check env file, Postgres, migrations, TWS
task validate -- --no-tws     # Skip TWS connectivity check
```

To use 1Password, wrap any task command:

```bash
op run --env-file=.env.dev -- task api
op run --env-file=.env.dev -- task worker:jobs
```

To target production:

```bash
ENV=prod task api
```

## Further Reading

| Doc                                                              | Topic                                                |
| ---------------------------------------------------------------- | ---------------------------------------------------- |
| [install-python-and-frontend.md](install-python-and-frontend.md) | Concise install and startup commands                 |
| [download-positions.md](download-positions.md)                   | Position sync and account aliases                    |
| [contract-ref-setup.md](contract-ref-setup.md)                   | Contract caching and sync architecture               |
| [secrets-using-1password.md](secrets-using-1password.md)         | 1Password CLI integration                            |
| [tradebot-chatbot.md](tradebot-chatbot.md)                       | Tradebot architecture, tools, and safety constraints |
| [tradebot-workers.md](tradebot-workers.md)                       | Worker processes, heartbeats, and job dispatch       |
| [index.md](_index.md)                                            | Full documentation index                             |
