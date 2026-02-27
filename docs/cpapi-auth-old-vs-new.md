# IBKR CPAPI/Web API Auth: Old vs New

This note explains the transition from the older "Client Portal API (CPAPI)" framing to the newer "IBKR Web API" framing, with focus on auth/session behavior.

## TL;DR

- IBKR is consolidating docs and naming under **IBKR Web API**.
- Existing CPAPI-style endpoints are still widely used.
- The old `POST /iserver/reauthenticate` path is deprecated.
- Use the newer brokerage-session init path (`/iserver/auth/ssodh/init`) and keep session alive with `/tickle`.

## Old Way (Legacy CPAPI Pattern)

Typical flow many scripts used:

1. Start local Client Portal Gateway and log in via browser.
2. Check auth/session with `POST /iserver/auth/status`.
3. If needed, call `POST /iserver/reauthenticate`.
4. Call `iserver` and `portfolio` endpoints.
5. Periodically call `POST /tickle`.

Notes:

- This flow often "worked until it didn't" around session boundaries.
- `reauthenticate` is the key legacy piece to stop relying on.

## New Way (Current Recommended Pattern)

Use this high-level flow:

1. Start gateway and complete browser login.
2. Check `POST /iserver/auth/status`.
3. Initialize brokerage session via `POST /iserver/auth/ssodh/init` when required.
4. Call target endpoints (for example watchlists and portfolio data).
5. Keep alive with `POST /tickle`.
6. On session expiry, repeat status check + session init.

## Watchlists Implication

- Watchlist endpoints remain in the `iserver` surface (for example list/get watchlists).
- For ngtrader, ingest these into local `watch_lists` and `watch_list_instruments`.
- Do not depend on TWS socket API for reading saved watchlist definitions; use Web API/CPAPI endpoints for that.

## Operational Guidance

- Treat auth as a session lifecycle, not one-time login.
- Always check session status before critical calls.
- Add explicit error handling for:
  - unauthenticated session
  - brokerage session not initialized
  - stale session requiring re-init
- Keep a heartbeat (`/tickle`) in any long-running sync worker.

## References

- IBKR CPAPI v1 docs: `https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/`
- IBKR Web API docs: `https://ibkrcampus.com/campus/ibkr-api-page/webapi-doc/`
- IBKR Web API changelog: `https://ibkrcampus.com/campus/ibkr-api-page/web-api-changelog/`
