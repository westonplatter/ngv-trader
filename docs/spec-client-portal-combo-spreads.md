# Spec: Client Portal Combo Spreads

## Purpose

Show CL calendar/time spreads using IBKR-native spread linkage instead of inferring leg pairs.

## Problem

- Current position sync uses `ib.positions()` and stores one row per leg.
- For a spread like short `CL Sep 2026` + long `CL Dec 2026`, ngtrader sees two independent legs.
- Operators need an explicit "these legs belong to one spread" view.

## Scope

- Add Client Portal API (CPAPI) integration for combo positions.
- Sync CPAPI combo positions into Postgres with idempotent upserts.
- Expose read API for spread-level and leg-level views.
- Add UI view optimized for CL calendar spreads.
- Preserve current TWS position sync; do not remove it.

## Non-goals

- Replacing TWS socket APIs for order placement.
- Auto-detecting spreads for all manually legged positions.
- Full multi-asset spread analytics.

## External Facts

- CPAPI provides `GET /portfolio/{accountId}/combo/positions`.
- Endpoint is intended for positions acquired as combinations.
- TWS socket `reqPositions` path remains leg-based.
- Flex reports can provide complex-position summaries for batch/audit use.

## Recommendation

Use a dual-source model:

- Source A (existing): TWS `ib.positions()` for fast leg snapshots.
- Source B (new): CPAPI combo positions for native spread linkage.

The UI should show CPAPI-linked spreads first, then unmatched legs separately.

## Setup (Individual Account, Local Gateway)

1. Install Java and IBKR Client Portal Gateway (`clientportal.gw`).
2. Run gateway locally (`bin/run.sh root/conf.yaml`).
3. Log in via browser at `https://localhost:<port>` with IBKR + 2FA.
4. Keep session alive with periodic `POST /tickle`.
5. Check auth via `POST /iserver/auth/status`.
6. Re-auth after daily session boundary when required.

## Proposed Env Vars

- `IBKR_CP_BASE_URL` (default `https://localhost:5000/v1/api`)
- `IBKR_CP_TIMEOUT_SECONDS` (default `15`)
- `IBKR_CP_TICKLE_INTERVAL_SECONDS` (default `60`)
- `IBKR_CP_VERIFY_TLS` (default `false` for local gateway)
- `IBKR_CP_ENABLED` (default `false`)

## Data Model

Add two tables.

### `combo_positions`

- `id` (pk)
- `account_id` (int, not null)
- `source` (text, not null, default `cpapi`)
- `combo_key` (text, not null)  
  Deterministic key from account + normalized leg `conid:ratio` set.
- `name` (text, nullable)
- `description` (text, nullable)
- `position` (float, nullable)
- `avg_price` (float, nullable)
- `market_value` (float, nullable)
- `unrealized_pnl` (float, nullable)
- `realized_pnl` (float, nullable)
- `raw` (jsonb, not null)
- `fetched_at` (timestamptz, not null)
- `created_at`, `updated_at` (timestamptz, not null)

Constraints/indexes:

- Unique `(account_id, source, combo_key)`
- Index `(account_id, fetched_at desc)`

### `combo_position_legs`

- `id` (pk)
- `combo_position_id` (int, not null)
- `con_id` (int, not null)
- `ratio` (float, nullable)
- `position` (float, nullable)
- `avg_price` (float, nullable)
- `market_value` (float, nullable)
- `unrealized_pnl` (float, nullable)
- `realized_pnl` (float, nullable)
- `raw` (jsonb, not null)
- `created_at`, `updated_at` (timestamptz, not null)

Constraints/indexes:

- Unique `(combo_position_id, con_id)`
- Index `(con_id)`

## Service Plan

Add `src/services/combo_position_sync.py`.

Core behavior:

- `check_combo_tables_ready(engine)` for migration guard.
- `sync_combo_positions_once(engine, base_url, timeout_seconds, verify_tls)`:
  - ensure CPAPI session is authenticated.
  - call `/portfolio/accounts`.
  - for each account call `/portfolio/{accountId}/combo/positions?nocache=true`.
  - upsert `combo_positions` + `combo_position_legs`.
  - mark stale rows for account snapshot (replace semantics per account).
  - return sync metrics.

Implementation note:

- Persist full payload in `raw` to protect against schema drift.
- Map only stable fields initially; add fields after observing live payloads.

## Jobs/Worker Plan

- Add job type `combo_positions.sync`.
- In `scripts/work_jobs.py`, map `combo_positions.sync` to `sync_combo_positions_once`.
- Optional: enqueue `combo_positions.sync` after `positions.sync`.
- Expose manual enqueue endpoint/tool for operator control.

## API Plan

Add router `src/api/routers/spreads.py`.

- `GET /api/v1/spreads`
  - filters: `account_id`, `symbol` (default `CL`), `limit`.
  - returns spread objects with nested legs.
- `GET /api/v1/spreads/{spread_id}`
- `GET /api/v1/spreads/unmatched-legs`
  - CL legs that are not part of any CPAPI combo snapshot.

## UI Plan

Add a `Spreads` view (new route) or a second tab in `Positions`.

Primary table columns:

- Account
- Spread name/description
- Net position
- Legs (e.g., `-1 CLU6 / +1 CLZ6`)
- Avg price
- Unrealized PnL
- Last synced at

Interaction:

- Expand row to show leg-level metrics.
- Badge: `Native Combo` vs `Unmatched Legs`.

## Operational Constraints

- CPAPI session requires interactive login and periodic re-auth.
- Gateway must run on same machine as browser login for individual accounts.
- When session is invalid, API should return clear actionable errors (`Re-auth required`).

## Rollout

1. Add migration + ORM models.
2. Implement CPAPI client + sync service.
3. Add `combo_positions.sync` worker wiring.
4. Add read API endpoints.
5. Add frontend `Spreads` UI.
6. Add operator runbook for gateway login/reauth.

## Acceptance Criteria

- Spread opened as combo in IBKR appears in ngtrader as one spread with linked legs.
- Re-running sync is idempotent (no duplicate combos/legs).
- Unauthenticated CPAPI session produces explicit, operator-actionable error.
- `/positions` still works unchanged for leg-level monitoring.
- CL spread screen shows both native combos and unmatched CL legs.

## Risks and Mitigations

- Session churn and re-auth friction.
  - Mitigation: surface session status + lightweight runbook.
- Not all manual legged positions appear as combos.
  - Mitigation: unmatched-legs view remains available.
- CPAPI payload shape drift.
  - Mitigation: keep `raw` payload and conservative field mapping.

## References

- IBKR CPAPI v1: `https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/`
- IBKR Web API changelog: `https://ibkrcampus.com/campus/ibkr-api-page/web-api-changelog/`
- TWS complex positions guide: `https://ibkrguides.com/tws/usersguidebook/realtimeactivitymonitoring/complexpositions.htm`
- TWS API positions docs: `https://interactivebrokers.github.io/tws-api/positions.html`
- Flex complex positions report: `https://www.ibkrguides.com/reportingreference/reportguide/complexpositions_fq.htm`
