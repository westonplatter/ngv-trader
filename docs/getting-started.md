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

| Component              | Purpose                                                                                                                                                                    |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Frontend**           | React/TypeScript UI for viewing positions, orders, trades, watchlists, and the Tradebot chat                                                                               |
| **Backend**            | FastAPI REST API serving data from Postgres and proxying LLM chat                                                                                                          |
| **Workers**            | Background processes that sync data (positions, contracts, quotes) with IBKR                                                                                               |
| **PostgreSQL**         | Stores accounts, positions, orders, trades, contracts, watchlists, and jobs                                                                                                |
| **IBKR TWS / Gateway** | Interactive Brokers connection for live market data (required only for the optional [intraday TWS overlay](core/intraday-tws-overlay.md); FlexQuery sync needs no session) |

## Prerequisites

Install these before proceeding:

| Tool                   | Version  | Install                                                                                                                                                                          |
| ---------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `uv`                   | latest   | `curl -LsSf https://astral.sh/uv/install.sh \| sh`                                                                                                                               |
| Bun                    | 1.0+     | [bun.sh](https://bun.sh/)                                                                                                                                                        |
| PostgreSQL             | 14+      | [postgresql.org](https://www.postgresql.org/download/) or `brew install postgresql`                                                                                              |
| Task                   | latest   | [taskfile.dev](https://taskfile.dev/docs/installation)                                                                                                                           |
| 1Password CLI (`op`)   | latest   | [developer.1password.com](https://developer.1password.com/docs/cli/get-started/) — required for `task api`/`worker:jobs`/`worker:orders`; other tasks load the env file directly |
| IBKR TWS or IB Gateway | optional | [interactivebrokers.com](https://www.interactivebrokers.com/en/trading/tws.php)                                                                                                  |

## 1. Clone and Install Dependencies

```bash
git clone <repo-url> ngv-trader
cd ngv-trader
```

Most of the repo's history is committed UI screenshots. If you don't need it,
`--depth 1` clones ~1.7M instead of ~6.5M:

```bash
git clone --depth 1 <repo-url> ngv-trader
```

Unshallow later with `git fetch --unshallow`.

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

# Encryption key for the IBKR Flex Query tokens stored in the database.
# Required for trades/positions FlexQuery sync — see workers.md
# FLEX_TOKEN_ENCRYPTION_KEY=op://Vault/FLEX_TOKEN_ENCRYPTION_KEY/value

# Tradebot LLM (optional — needed only for the chat feature)
# TRADEBOT_LLM_API_KEY=sk-...
# TRADEBOT_LLM_MODEL=gpt-5-mini
# TRADEBOT_LLM_BASE_URL=https://api.openai.com/v1
# TRADEBOT_LLM_TIMEOUT_SECONDS=45
```

### Secrets with 1Password (optional)

If you use 1Password, values in `.env.dev` can reference secrets with `op://` URIs instead of plain text:

```bash
DB_PASSWORD=op://MyVault/ngtrader-db/password
BROKER_TWS_PORT=op://MyVault/ibkr/tws-port
```

To resolve `op://` references, wrap scripts that don't use the task runner directly:

```bash
op run --env-file=.env.dev -- uv run python scripts/setup_db.py --env dev
```

`op run` resolves the references and injects the real values as environment variables before the inner command starts. Only `task api`, `task worker:jobs`, and `task worker:orders` embed `op run` internally — run those directly. `task migrate`, `task migrate:down`, `task migrate:new`, and `task validate` load `.env.<ENV>` themselves but do not wrap `op run`, so prefix them with `op run --env-file=.env.dev -- ...` if your env file has `op://` references. `task frontend` and `task frontend:install` don't read `.env.dev`/`.env.prod` at all.

See [secrets-using-1password.md](secrets-using-1password.md) for details.

If you do **not** use 1Password, just use plain values in `.env.dev` and run commands directly.

### FlexQuery tokens

IBKR FlexQuery credentials are **not** environment variables. Each token lives
as a row in the `flexquery_tokens` table, encrypted at rest with Fernet, next to
the report id it requests. `FLEX_TOKEN_ENCRYPTION_KEY` — a comma-separated list
of Fernet keys, newest first — is the only related value in `.env.<env>`.

One token can cover several IBKR accounts. Sync stamps each account row with the
token it was discovered under (`accounts.flex_query_token_id`), so the mapping
lives in the database rather than in an operator's head. Every active token is
used on each sync run.

Day-to-day management lives in the UI, on the **Accounts** page: the FlexQuery
Tokens table above the accounts list adds tokens, edits their alias and report
id, and activates or deactivates them. The token value is write-only — it is
never sent back to the browser, so changing one means typing a replacement.

The encryption key never passes through the UI. Generate and rotate it with
`scripts/manage_flex_tokens.py` (run it with `--help`), which also offers the
same add/list/deactivate actions for headless use. First-time setup, before the
API can store anything:

```bash
uv run python scripts/manage_flex_tokens.py generate-key --out newkey.txt
# put that value in 1Password, point FLEX_TOKEN_ENCRYPTION_KEY at it, delete the file
uv run python scripts/manage_flex_tokens.py verify
```

On the CLI the token is read from a hidden prompt or stdin, never an argument,
and is never printed back. To rotate the encryption key, prepend a new key to
`FLEX_TOKEN_ENCRYPTION_KEY`, run `rotate-key`, confirm `verify` passes, then drop
the old key. Losing the key with no copy makes every stored token unreadable —
IBKR tokens are re-issuable from the client portal, so that means re-seeding, not
permanent data loss.

Both `worker:jobs` (which decrypts to sync) and the API (which encrypts on write)
need `FLEX_TOKEN_ENCRYPTION_KEY`. Reads never decrypt, so listing tokens works
without it.

## 3. Set Up PostgreSQL

Make sure PostgreSQL is running, then create the database and run migrations:

```bash
uv run python scripts/setup_db.py --env dev
```

This script:

1. Connects to the `postgres` maintenance database
2. Creates `ngtrader_dev` (or whatever `DB_NAME` is set to) if it doesn't exist
3. Runs all Alembic migrations to bring the schema up to date

You can also run migrations independently. `task` commands default to `ENV=prod` (per `Taskfile.yaml`), so pass `ENV=dev` explicitly for local work:

```bash
ENV=dev task migrate
```

## 4. Validate Your Setup

Run the environment validator to confirm everything is wired up correctly:

```bash
ENV=dev task validate
```

This checks your `.env.dev` file, PostgreSQL connectivity, migration status, and TWS connectivity. To skip the TWS check if you don't have IBKR running:

```bash
ENV=dev task validate -- --no-tws
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

This connects to IBKR, fetches all positions across your managed accounts, creates `Account` rows, and upserts positions into the `positions` table. This is a one-time bootstrap; ongoing settled position and trade sync runs through the FlexQuery jobs in `worker:jobs` (see [workers.md](workers.md)).

A live TWS/Gateway session also powers the on-demand **real-time intraday overlay** (live quantity, marks, and today's realized P&L layered on the settled FlexQuery snapshot), triggered by the **Refresh Live (TWS)** button on the Positions and Strategies pages. See [intraday TWS overlay](core/intraday-tws-overlay.md).

## 6. Start the Application

You need to start the backend and frontend. In two separate terminals:

**Terminal 1 — Backend API (port 8000):**

```bash
ENV=dev task api
```

The API validates the database connection on startup. If PostgreSQL is unreachable, you'll see a clear error message immediately instead of a silent failure.

**Terminal 2 — Frontend dev server (port 5173):**

```bash
task frontend
```

Or start both at once:

```bash
ENV=dev task dev
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

**Terminal 3 — Jobs worker** (FlexQuery trade/position sync, contract sync, watchlist quotes, real-time TWS overlay):

```bash
ENV=dev task worker:jobs
```

`worker:jobs` dispatches every job type by `job_type`. A live TWS/Gateway session is required for contract-metadata sync, watchlist quotes, and the real-time intraday TWS overlay (`intraday.sync.tws`, triggered by the **Refresh Live (TWS)** button on the Positions and Strategies pages — see [intraday TWS overlay](core/intraday-tws-overlay.md)). FlexQuery trade/position sync (the active settled-sync path) works without a session as long as at least one token is seeded (see [FlexQuery tokens](#flexquery-tokens) above). The UI header shows worker health lights (green/yellow/red) based on heartbeat freshness.

See [workers.md](workers.md) for worker architecture details.

## 7. Using the Application

### Pages

| Page            | URL            | What it does                                              |
| --------------- | -------------- | --------------------------------------------------------- |
| **Tradebot**    | `/tradebot`    | AI chat interface — ask about positions, trigger syncs    |
| **Accounts**    | `/accounts`    | View IBKR accounts and set display aliases                |
| **Positions**   | `/positions`   | View current holdings with filters, trigger position sync |
| **Orders**      | `/orders`      | View synced orders and track fill status                  |
| **Trades**      | `/trades`      | View executed trade history and fill details              |
| **Strategies**  | `/strategies`  | Organize executions into trade groups with strategy tags  |
| **Watch Lists** | `/watchlists`  | Create watchlists, add instruments, view live quotes      |
| **Market Data** | `/market-data` | Monitor futures and options market data                   |
| **Structures**  | `/structures`  | Build and price options structures; view expected PnL     |

### Common workflows

**Sync positions from IBKR:**

- Click the sync button on the Positions page, or
- Ask the Tradebot: "sync my positions"

**View live quotes:**

- Create a watchlist on the Watch Lists page
- Add instruments (stocks, futures, options)
- Quotes auto-refresh while the page is open (requires `worker:jobs` running)

**View live intraday P&L (real-time TWS overlay):**

- Click **Refresh Live (TWS)** on the Positions or Strategies page
- Requires a running TWS/Gateway session and `worker:jobs`
- Overlays live quantity, blended cost, marks, and today's realized P&L on the settled (T-1) FlexQuery snapshot; degrades silently to settled values when no session is available (see [intraday TWS overlay](core/intraday-tws-overlay.md))

**Fetch contract metadata:**

- Ask the Tradebot: "what CL futures are available?"
- It will look up cached contracts or trigger a sync if needed

### Tradebot chat

The Tradebot is an LLM-powered assistant that can read your portfolio data and take actions. It requires `TRADEBOT_LLM_API_KEY` to be set in your env file.

Available commands include listing accounts/positions/orders, syncing positions and contracts, and managing watchlists. See [tradebot-chatbot.md](tradebot-chatbot.md) for the full tool list.

## Quick Reference: Task Commands

These default to `ENV=prod` (per `Taskfile.yaml`) — prefix each with `ENV=dev` to target your local setup instead:

```bash
task list              # Show all available tasks
ENV=dev task api               # Start FastAPI backend (port 8000)
task frontend          # Start Vite frontend (port 5173)
ENV=dev task dev               # Start both API and frontend
task frontend:install  # bun install for frontend
ENV=dev task migrate           # Run Alembic migrations to head
ENV=dev task migrate:down      # Roll back one migration
ENV=dev task migrate:new -- "description"  # Create a new migration
ENV=dev task worker:jobs       # Start jobs worker (position sync, quotes)
ENV=dev task validate          # Check env file, Postgres, migrations, TWS
ENV=dev task validate -- --no-tws     # Skip TWS connectivity check
```

## Troubleshooting

### Worker fails with `ConnectionRefusedError` on port 7496/7497

```
ib_async.client ERROR API connection failed: ConnectionRefusedError(61, "Connect call failed ('127.0.0.1', 7496)")
```

Nothing is listening on the IBKR API port. Check, in order:

1. **TWS or IB Gateway is running** and you are logged in.
2. **API access is enabled**: Edit > Global Configuration > API > Settings > **"Enable ActiveX and Socket Clients"** must be checked.
3. **Socket port matches your env**: 7497 = TWS paper, 7496 = TWS live, 4002 = Gateway paper, 4001 = Gateway live. `BROKER_TWS_PORT` in your env file must match what TWS is listening on.
4. **`127.0.0.1` is in Trusted IPs** (same API settings screen).

Verify nothing-vs-something on the port:

```bash
lsof -nP -iTCP:7496 -sTCP:LISTEN   # or 7497 for paper
```

Empty output = TWS not listening; fix on the TWS side.

## Further Reading

| Doc                                                            | Topic                                                 |
| -------------------------------------------------------------- | ----------------------------------------------------- |
| [contract-ref-setup.md](contract-ref-setup.md)                 | Contract caching and sync architecture                |
| [trades-and-executions-sync.md](trades-and-executions-sync.md) | Trade/position sync (FlexQuery), spreads, corrections |
| [secrets-using-1password.md](secrets-using-1password.md)       | 1Password CLI integration                             |
| [tradebot-chatbot.md](tradebot-chatbot.md)                     | Tradebot architecture, tools, and safety constraints  |
| [workers.md](workers.md)                                       | Worker processes, heartbeats, and job dispatch        |
| [\_index.md](_index.md)                                        | Full documentation index                              |
