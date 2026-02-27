# Runbook: IBKR Client Portal Gateway

Operator guide for running the IBKR Client Portal Gateway locally to enable combo/spread position syncing.

## Prerequisites

- **Java** installed and on PATH (`java -version` to verify)
- Gateway files at `clientportal.gw/` in the project root
- IBKR account credentials + 2FA device

## 1. Start the Gateway

```bash
cd clientportal.gw
bin/run.sh root/conf.yaml
```

The gateway starts on **port 5000** (configured in `root/conf.yaml` via `listenPort`).

You'll see log output confirming startup. Leave this terminal running.

## 2. Log In

Open a browser and navigate to:

```
https://localhost:8888
```

Your browser will warn about the self-signed certificate — accept it and proceed.

1. Enter your IBKR username and password.
2. Complete 2FA on your device.
3. You should see a confirmation page once authenticated.

## 3. Verify Authentication

From another terminal:

```bash
curl -k -X POST https://localhost:8888/v1/api/iserver/auth/status
```

Expected response when authenticated:

```json
{"authenticated": true, "competing": false, "connected": true, ...}
```

If `"authenticated": false`, re-do the browser login.

## 4. Keep the Session Alive

The CPAPI session expires after a period of inactivity. Send a tickle periodically:

```bash
curl -k -X POST https://localhost:8888/v1/api/tickle
```

For automated keep-alive, you can run a cron or loop:

```bash
while true; do curl -sk -X POST https://localhost:8888/v1/api/tickle > /dev/null; sleep 55; done
```

The spec proposes `IBKR_CP_TICKLE_INTERVAL_SECONDS=60` for an in-app heartbeat (not yet implemented as a background task).

## 5. Test Combo Positions Endpoint

Fetch your account list:

```bash
curl -k https://localhost:8888/v1/api/portfolio/accounts
```

Then fetch combo positions for an account:

```bash
curl -k "https://localhost:8888/v1/api/portfolio/ACCOUNT_ID/combo/positions?nocache=true"
```

Replace `ACCOUNT_ID` with your actual account ID from the previous call.

## 6. Configure ngtrader

Add to your `.env.dev` (or `.env.prod`):

```bash
IBKR_CP_BASE_URL=https://localhost:8888/v1/api
IBKR_CP_TIMEOUT_SECONDS=15
IBKR_CP_VERIFY_TLS=false
```

## 7. Run a Combo Sync

From the UI: go to the **Spreads** page and click **Sync Combo Positions**.

Or enqueue manually via API:

```bash
curl -X POST http://localhost:8000/api/v1/spreads/sync \
  -H "Content-Type: application/json" \
  -d '{"source": "manual-cli"}'
```

Then run the job worker (if not already running):

```bash
uv run python scripts/work_jobs.py --env dev --once
```

## Daily Session Boundary

IBKR resets sessions daily (typically around 23:45 ET). After reset:

1. The sync job will fail with: `CPAPI session is not authenticated. Log in at the Client Portal Gateway and complete 2FA.`
2. Re-open `https://localhost:8888` in your browser and log in again.
3. Re-run the sync.

## Troubleshooting

| Symptom                              | Fix                                                                                                                                |
| ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------- |
| `CPAPI session is not authenticated` | Browser login at `https://localhost:8888`, complete 2FA                                                                            |
| `Connection refused` on port 5000    | Start the gateway: `cd clientportal.gw && bin/run.sh root/conf.yaml`                                                               |
| `SSL certificate problem`            | Expected — use `IBKR_CP_VERIFY_TLS=false` (default)                                                                                |
| Empty combo positions response `[]`  | You have no positions opened as combos in IBKR. Manually legged positions won't appear here — check the Unmatched Legs tab instead |
| `java: command not found`            | Install Java (e.g., `brew install openjdk`) and add to PATH                                                                        |

## Gateway Config Reference

The gateway config lives at `clientportal.gw/root/conf.yaml`. Key settings:

- `listenPort: 5000` — change if port 5000 is in use
- `listenSsl: true` — the gateway uses HTTPS with a self-signed cert
- `ips.allow` — IP allowlist; `127.0.0.1` is included by default
