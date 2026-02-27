# Spec: Combo Spreads

## Purpose

Show CL calendar/time spreads as linked spread objects instead of independent legs.

## Problem

- Position sync uses `ib.positions()` and stores one row per leg.
- For a spread like short `CL Sep 2026` + long `CL Dec 2026`, ngtrader sees two independent legs.
- Operators need an explicit "these legs belong to one spread" view.

## What We Tried

### Approach 1: CPAPI combo positions (abandoned)

Original plan was to use the IBKR Client Portal Gateway API
(`GET /portfolio/{accountId}/combo/positions`) to get native spread linkage.

**Why we abandoned it:**

- The Client Portal Gateway is a separate Java service that must run alongside TWS.
  Another process to manage, monitor, and keep alive.
- Gateway requires interactive browser login + 2FA, with daily session re-auth.
  High operator friction for an individual account setup.
- The downloaded gateway (April 2023 build) returned `Bad Request` errors
  from IBKR's Akamai CDN on all API calls after successful browser login.
  The beta gateway had the same issue. Likely a version/compatibility problem.
- Port 5000 conflicts with macOS AirPlay Receiver (ControlCenter).
  Required port changes across all configs.
- Even if the gateway worked, the CPAPI combo endpoint only returns positions
  **acquired as combinations** (BAG orders). It would not help for positions
  legged in individually.

### Approach 2: TWS BAG detection (no data)

Rewrote the sync to detect `secType == "BAG"` positions from `ib.positions()`.

**What we learned:**

- `ib.positions()` returns `secType` values: `FUT`, `STK`, `OPT`, `FOP`.
  **No BAG positions were returned** despite having active spreads.
- TWS only reports BAG positions when the spread was submitted as a combo/BAG order.
  Spreads legged in individually (which is the common case for CL calendar spreads)
  appear as separate FUT positions with no linkage.
- `contract.comboLegs` is always empty for non-BAG positions.

### Approach 3: Infer spreads from execution data (next step)

Since neither IBKR source provides native linkage for individually legged spreads,
we need to infer spread membership from execution/order data.

**Plan:**

- Import execution data (trades/fills) into ngtrader.
- Match legs that were executed as part of the same spread based on:
  - Same symbol (e.g., CL)
  - Opposite sides (BUY + SELL)
  - Different expiries (calendar spread structure)
  - Close execution timestamps (submitted together or within a window)
  - Or: explicit operator tagging at order submission time
- Populate the existing `combo_positions` + `combo_position_legs` tables
  with `source="inferred"` or `source="tagged"`.

## What's Built (ready to use)

### Data Model

Two tables, migrated and live:

**`combo_positions`** — one row per spread

- `id`, `account_id`, `source`, `combo_key` (deterministic from legs)
- `name`, `description`, `position`, `avg_price`
- `market_value`, `unrealized_pnl`, `realized_pnl`
- `raw` (jsonb), `fetched_at`, `created_at`, `updated_at`
- Unique: `(account_id, source, combo_key)`

**`combo_position_legs`** — one row per leg in a spread

- `id`, `combo_position_id` (FK cascade to parent), `con_id`, `ratio`
- `position`, `avg_price`, `market_value`, `unrealized_pnl`, `realized_pnl`
- `raw` (jsonb), `created_at`, `updated_at`
- Unique: `(combo_position_id, con_id)`

### Service

`src/services/combo_position_sync.py` — currently wired to detect BAG positions
from TWS. Will be updated to support execution-based inference.

### Worker

Job type `combo_positions.sync` registered in `scripts/work_jobs.py`.
Uses TWS connection params (host, port, client_id).

### API

Router: `src/api/routers/spreads.py`

| Method | Path                             | Description                                                            |
| ------ | -------------------------------- | ---------------------------------------------------------------------- |
| `GET`  | `/api/v1/spreads`                | List combos with nested legs. Filters: `account_id`, `symbol`, `limit` |
| `GET`  | `/api/v1/spreads/{spread_id}`    | Single spread detail                                                   |
| `GET`  | `/api/v1/spreads/unmatched-legs` | Positions not in any combo. Filter: `symbol` (default `CL`)            |
| `POST` | `/api/v1/spreads/sync`           | Enqueue a `combo_positions.sync` job                                   |

### Frontend

`frontend/src/components/SpreadsTable.tsx` at `/spreads` route.

- Two tabs: "Native Combos" and "Unmatched CL Legs" with counts.
- Expandable rows showing leg-level detail.
- Sync button to enqueue combo sync job.

### Taskfile

`task gateway` command exists but is not needed with the TWS-only approach.

## Key Lessons for Next Time

1. **CPAPI is not worth the operational cost for individual accounts.**
   The gateway is a separate Java process requiring browser login, 2FA,
   daily re-auth, and periodic tickle keep-alive. Too much friction.

2. **TWS `ib.positions()` never returns BAG for individually legged spreads.**
   Only positions submitted as a BAG/combo order get `secType=BAG` and `comboLegs`.
   Most CL calendar spreads are legged in individually.

3. **Spread inference must come from execution data, not position data.**
   Positions are stateless snapshots. Executions carry the context of
   what was traded together.

4. **macOS port 5000 is taken by AirPlay Receiver (ControlCenter).**
   If the gateway is ever needed again, use port 8888.

5. **The combo tables use a FK with cascade delete** (`combo_position_legs.combo_position_id`
   → `combo_positions.id`). This is the first FK in the codebase. Monitor for any
   friction and remove if needed.

6. **`httpx` was added as a dependency** for the original CPAPI client.
   It's no longer used by the combo sync but remains available.

## Acceptance Criteria (updated)

- Spreads inferred from execution data appear as linked combos with legs.
- Re-running sync is idempotent (no duplicate combos/legs).
- `/positions` still works unchanged for leg-level monitoring.
- Spreads UI shows both linked combos and unmatched legs.

## References

- TWS API positions docs: `https://interactivebrokers.github.io/tws-api/positions.html`
- TWS complex positions guide: `https://ibkrguides.com/tws/usersguidebook/realtimeactivitymonitoring/complexpositions.htm`
- IBKR CPAPI v1: `https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/`
- Flex complex positions report: `https://www.ibkrguides.com/reportingreference/reportguide/complexpositions_fq.htm`
