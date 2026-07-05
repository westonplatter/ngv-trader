---
title: "refactor: Make Flex Query the only active sync path; rename TWS vs Flex symbols/routes explicitly"
type: refactor
status: shipped
created: 2026-05-13
---

# refactor: Make Flex Query the only active sync path; rename TWS vs Flex symbols/routes explicitly

## Summary

The IBKR background worker currently dispatches both TWS-backed sync jobs (`positions.sync`, `trades.sync`) and Flex Query sync jobs (`positions.flex_sync`, `trades.flex_sync`). Going forward, only the Flex Query path should be active in the worker and exposed by the UI. The TWS code path (handlers, API endpoints, services) must remain in the codebase so it can be reactivated when real-time TWS data fetching is added back later.

To make the two paths unambiguous wherever they appear, the Python constants, HTTP routes, **and the persisted `Job.job_type` string values** will all be renamed to carry explicit `_TWS` / `_FLEXQUERY` (and `/sync/tws` / `/sync/flex-query`, and `.tws` / `.flexquery`) markers. A small Alembic migration backfills existing `jobs` rows from the old strings to the new ones in one transaction.

The standalone `scripts/fetch_flex_trades.py` script is the inspiration for the worker behavior, but the worker already calls `fetch_flex_report` + `sync_flex_trades` from `src/services/flex_trade_sync.py`. No script-to-worker code lift is required.

---

## Problem Frame

- Two parallel sync stacks (TWS and Flex Query) exist for both trades and positions.
- Today the worker dispatcher and the UI surface both, so it's easy to enqueue a TWS-backed sync that the user no longer wants run.
- The TWS path should not be deleted — it's the future home of real-time data — just deactivated.
- Naming today (`JOB_TYPE_POSITIONS_SYNC` vs `JOB_TYPE_FLEX_POSITIONS_SYNC`, `/positions/sync` vs `/positions/flex-sync`) makes the TWS vs Flex distinction implicit. After this refactor it should be explicit at every layer.

## Scope

In scope:
- Rename Python `JOB_TYPE_*` constants for the four sync job types to carry `_TWS` or `_FLEXQUERY` suffix.
- Rename the four `/trades/...` and `/positions/...` sync API routes to carry `/sync/tws` and `/sync/flex-query` path segments.
- **Move the worker's handler module out of `scripts/` and into `src/workers/`**, so the dispatcher and all `handle_*` functions live with the rest of the application code; `scripts/work_jobs.py` becomes a thin CLI entrypoint that imports from `src/workers/jobs.py`.
- Remove the two TWS entries from the worker dispatcher's `handlers` map (post-move, in `src/workers/jobs.py`) — keep the handler functions defined.
- Update the frontend trades and positions tables to call the Flex Query routes.
- **Push the TWS / Flex Query distinction down into the services layer**: rename `src/services/trade_sync.py`, `position_sync.py`, and `order_sync.py` to carry `_tws` suffixes, and `flex_trade_sync.py` / `flex_position_sync.py` to carry `_flexquery` suffixes. Update all importers. No behavior changes inside the renamed files — TWS code remains intact and importable for future reactivation.
- **Rename the four sync handler functions** to carry explicit suffixes so they match the constant / route / service-module naming: `handle_trades_sync` → `handle_trades_sync_tws`, `handle_positions_sync` → `handle_positions_sync_tws`, `handle_flex_trades_sync` → `handle_trades_sync_flexquery`, `handle_flex_positions_sync` → `handle_positions_sync_flexquery`. Bodies unchanged; TWS handlers remain importable for future reactivation. The non-sync handlers (`handle_contracts_sync`, `handle_order_fetch_sync`, etc.) keep their existing names — they're not part of the TWS-vs-Flex split.
- **Extract shared row-coercion / account-upsert helpers into `src/services/sync_common.py`** so the `*_flexquery` modules no longer cross-import from the `*_tws` modules. Functions moved: `_safe_float`, `_safe_int`, `_safe_str` (currently in `trade_sync.py`) and `get_or_create_accounts` (currently in `position_sync.py`). Bodies unchanged.
- **Rename the persisted `Job.job_type` string values** to match the new explicit constant names. Add an Alembic migration that backfills existing `jobs` rows: `"positions.sync"` → `"positions.sync.tws"`, `"positions.flex_sync"` → `"positions.sync.flexquery"`, `"trades.sync"` → `"trades.sync.tws"`, `"trades.flex_sync"` → `"trades.sync.flexquery"`. The migration runs in a single transaction; the worker is briefly stopped during deploy so no claim races a string-value flip.

Out of scope (deferred):
- Adding a new toggle or per-account selection mechanism in the UI for Flex Query (the existing button just enqueues a flex job).
- Migrating `flex_sync_log` schema or any historical reconciliation.
- Changes to `scripts/fetch_flex_trades.py` — that is a one-off manual diagnostic / report-printing CLI, not core application logic, and stays in `scripts/`.
- Other unrelated `scripts/*` files (`download_positions.py`, `work_order_queue.py`, etc.) — they will keep working through their importer updates (U5) but their own placement is not part of this change.

---

## Key Technical Decisions

- **Rename `Job.job_type` string values too — backfilled by Alembic.** The persisted strings move from `"positions.sync"` / `"positions.flex_sync"` / `"trades.sync"` / `"trades.flex_sync"` to `"positions.sync.tws"` / `"positions.sync.flexquery"` / `"trades.sync.tws"` / `"trades.sync.flexquery"`. Rationale: now that we're renaming the Python constants, leaving the strings on the legacy form would create a permanent mismatch between code and DB; we'd rather take a one-time migration. Naming follows the existing `domain.action` convention by extending to `domain.action.source`.
- **Single transactional migration; worker stopped during deploy.** The Alembic migration backfills all four string variants in one transaction. The deploy sequence (worker stop → migrate → code deploy → worker start) ensures no claim sees a half-renamed table.
- **Deactivate TWS at the dispatcher, not the API.** Both API endpoints continue to exist (renamed for clarity), but only the Flex Query endpoints are called by the UI, and only the Flex Query handlers are registered in `get_handler()`. A TWS job enqueued through the `/sync/tws` route will sit in `queued` status (no handler) — this is the intentional "off" state and is reversible with one line.
- **Shared sync helpers live in `src/services/sync_common.py`.** Row-coercion and account-upsert helpers were historically in `trade_sync.py` / `position_sync.py` (the TWS modules) because the Flex modules were added later. Now that the TWS/Flex split is explicit, the shared helpers move to a neutral module so neither side cross-imports the other.
- **Single coordinated rename pass.** Constants, importers, API routes, service modules, handler functions, frontend `fetch` paths, and the DB migration land together so the system never half-renames.
- **Frontend keeps the existing button as-is.** The button on `PositionsTable.tsx` / `TradesTable.tsx` just changes which URL it POSTs to. No UI label rewrite or new affordance.

---

## Existing Patterns to Follow

- `src/services/jobs.py` already centralizes `JOB_TYPE_*` constants — keep doing that.
- API routers follow the FastAPI `@router.post(...)` + `enqueue_job(...)` + `db.commit()` shape. Mirror the existing flex-sync route handlers exactly (`src/api/routers/trades.py:814`, `src/api/routers/positions.py:172`).
- Worker dispatch lives in `scripts/work_jobs.py:get_handler` — single dict, no abstraction.
- Frontend "kick off sync" buttons follow the pattern in `frontend/src/components/PositionsTable.tsx:223` (`kickOffPositionSync`) and `frontend/src/components/TradesTable.tsx:586` (`kickOffTradesSync`).

---

## Implementation Units

### U1. Rename `JOB_TYPE_*` constants in `src/services/jobs.py`

**Goal:** Introduce the explicit TWS / FLEXQUERY naming at the source of truth.

**Files:**
- `src/services/jobs.py`

**Approach:**
- Replace `JOB_TYPE_POSITIONS_SYNC = "positions.sync"` with `JOB_TYPE_POSITIONS_SYNC_TWS = "positions.sync.tws"`.
- Replace `JOB_TYPE_FLEX_POSITIONS_SYNC = "positions.flex_sync"` with `JOB_TYPE_POSITIONS_SYNC_FLEXQUERY = "positions.sync.flexquery"`.
- Replace `JOB_TYPE_TRADES_SYNC = "trades.sync"` with `JOB_TYPE_TRADES_SYNC_TWS = "trades.sync.tws"`.
- Replace `JOB_TYPE_FLEX_TRADES_SYNC = "trades.flex_sync"` with `JOB_TYPE_TRADES_SYNC_FLEXQUERY = "trades.sync.flexquery"`.
- Both the symbol *and* the string value change. The corresponding `jobs.job_type` rows are backfilled by U8's Alembic migration so existing data still resolves.

**Patterns to follow:** Existing constant block at top of `src/services/jobs.py`.

**Test scenarios:** *Test expectation: none — pure constant rename with values preserved; coverage comes from U2/U3/U4 importers compiling and the dispatcher integration test in U3.*

**Verification:** `uv run python -c "from src.services.jobs import JOB_TYPE_POSITIONS_SYNC_TWS, JOB_TYPE_POSITIONS_SYNC_FLEXQUERY, JOB_TYPE_TRADES_SYNC_TWS, JOB_TYPE_TRADES_SYNC_FLEXQUERY"` succeeds; ripgrep finds no remaining references to the old four constant names anywhere under `src/` or `scripts/`.

---

### U2. Update API routers to use the renamed constants and `/sync/tws` & `/sync/flex-query` paths

**Goal:** Make the HTTP surface match the explicit naming. Both the TWS and Flex Query routes remain reachable; only the URL changes.

**Dependencies:** U1.

**Files:**
- `src/api/routers/positions.py`
- `src/api/routers/trades.py`

**Approach:**
- `positions.py`:
  - Change route `@router.post("/positions/sync", ...)` to `@router.post("/positions/sync/tws", ...)`, and the constant reference from `JOB_TYPE_POSITIONS_SYNC` to `JOB_TYPE_POSITIONS_SYNC_TWS`.
  - Change route `@router.post("/positions/flex-sync", ...)` to `@router.post("/positions/sync/flex-query", ...)`, and the constant reference from `JOB_TYPE_FLEX_POSITIONS_SYNC` to `JOB_TYPE_POSITIONS_SYNC_FLEXQUERY`.
- `trades.py`: same pattern on `/trades/sync` → `/trades/sync/tws` and `/trades/flex-sync` → `/trades/sync/flex-query`.
- Request models (`PositionSyncRequest`, `FlexPositionSyncRequest`, `TradeSyncRequest`, `FlexTradeSyncRequest`) and response models are unchanged.
- Update the `from src.services.jobs import ...` import lines.

**Patterns to follow:** Existing endpoint handlers in the same files — `src/api/routers/trades.py:792` & `src/api/routers/trades.py:814`, `src/api/routers/positions.py:150` & `src/api/routers/positions.py:172`.

**Test scenarios:**
- POST `/positions/sync/tws` with a valid `PositionSyncRequest` body returns 202 and a `job_id`; the persisted `Job.job_type` equals `"positions.sync.tws"`.
- POST `/positions/sync/flex-query` with a valid `FlexPositionSyncRequest` body returns 202 and a `job_id`; the persisted `Job.job_type` equals `"positions.sync.flexquery"`.
- POST `/trades/sync/tws` and POST `/trades/sync/flex-query` likewise return 202 and persist `Job.job_type` of `"trades.sync.tws"` and `"trades.sync.flexquery"` respectively.
- POST `/positions/sync` (old path) returns 404. Same for `/positions/flex-sync`, `/trades/sync`, `/trades/flex-sync`.

**Verification:** `uv run pytest` on the routers passes; manual curl against a dev server confirms 202 on the new paths and 404 on the old ones.

---

### U6. Move worker handlers from `scripts/work_jobs.py` into `src/workers/jobs.py`

**Goal:** Treat the job dispatcher and `handle_*` functions as core application code. Leave `scripts/work_jobs.py` as a thin CLI entrypoint.

**Dependencies:** U1 (constant rename should be done first so the moved file picks up the new names in one pass). Best landed before U3 so U3 edits the new home.

**Files (new):**
- `src/workers/__init__.py` (empty package marker)
- `src/workers/jobs.py` (new home for handlers, dispatcher, and worker-local helpers)

**Files (modified):**
- `scripts/work_jobs.py` — slimmed down to a CLI shim

**Approach:**
- Create `src/workers/` as a new package next to `src/services/`, `src/api/`, etc.
- Move from `scripts/work_jobs.py` into `src/workers/jobs.py`:
  - All `handle_*` functions. **Rename the four sync handlers at move time** so the new file is the only place the new names ever existed:
    - `handle_positions_sync` → `handle_positions_sync_tws`
    - `handle_trades_sync` → `handle_trades_sync_tws`
    - `handle_flex_positions_sync` → `handle_positions_sync_flexquery`
    - `handle_flex_trades_sync` → `handle_trades_sync_flexquery`
  - Other handlers move with their existing names: `handle_contracts_sync`, `handle_contracts_chain_sync`, `handle_order_fetch_sync`, `handle_watchlist_add_instrument`, `handle_watchlist_quotes_refresh`, `handle_market_data_futures_prices`, `handle_market_data_futures_options`, `handle_market_data_snapshot`, `handle_contracts_qualify_and_snapshot`.
  - The `get_handler(job_type) -> Callable | None` function and its `handlers` dict (with map entries updated to the new function names).
  - Worker-local helpers that are not used outside this module: `_resolve_flex_credentials`, `resolve_tws_connection`, and any other private helpers currently defined in `scripts/work_jobs.py` solely to support the handlers.
  - The `JOB_TYPE_*` imports from `src.services.jobs`.
- Leave in `scripts/work_jobs.py`:
  - The `argparse` setup and `parse_args`.
  - Env loading (`load_env`, `check_db_ready`).
  - The polling loop in `main()` — `IBSessionPool` lifecycle, `claim_next_job`, `complete_job` / `fail_or_retry_job` wiring, `upsert_worker_heartbeat`.
  - `main()` calls `from src.workers.jobs import get_handler` and dispatches with that.
- Do not change function bodies during the move. This is a pure relocation; behavior changes happen in U3.
- Update any other module that imports a handler directly from `scripts.work_jobs` to instead import from `src.workers.jobs`. Identify with `rg "from scripts\\.work_jobs import|import scripts\\.work_jobs"`; today there are no production importers besides the shim itself, so this should be a small or zero-line change.

**Patterns to follow:**
- `src/services/` package layout (single-purpose modules, `__init__.py` empty).
- The split between "library code in `src/`" and "CLI entrypoint in `scripts/`" already used by `scripts/download_positions.py` calling into `src/services/position_sync.py`.

**Test scenarios:**
- `uv run python -c "from src.workers.jobs import get_handler"` succeeds.
- `uv run python -c "from src.workers.jobs import handle_trades_sync_tws, handle_trades_sync_flexquery, handle_positions_sync_tws, handle_positions_sync_flexquery"` succeeds.
- `uv run python -c "import scripts.work_jobs"` succeeds and `scripts.work_jobs.main` is still callable.
- `get_handler("positions.flex_sync")` returns `handle_positions_sync_flexquery`; `get_handler("trades.flex_sync")` returns `handle_trades_sync_flexquery`.
- `rg "def handle_" scripts/work_jobs.py` returns zero matches (all handler defs have moved).
- `rg "\\bhandle_(flex_)?trades_sync\\b|\\bhandle_(flex_)?positions_sync\\b" src scripts tests` returns zero matches (the old four function names are fully gone outside worktrees).
- Running the worker (`uv run python scripts/work_jobs.py --poll-seconds 1`) boots without import errors against the prod env and claims a previously-queued Flex Query job successfully.

**Verification:** Smoke-run the worker against a freshly enqueued Flex Query job; observe the handler executes from its new location (stack frames point at `src/workers/jobs.py`).

---

### U3. Deactivate TWS handlers in the worker dispatcher; keep handler functions

**Goal:** Make the worker process only Flex Query jobs; preserve TWS code path for future reactivation.

**Dependencies:** U1, U6.

**Files:**
- `src/workers/jobs.py` (after U6's move)

**Approach:**
- Confirm imports at the top of `src/workers/jobs.py` use the renamed constants (`JOB_TYPE_POSITIONS_SYNC_TWS`, `JOB_TYPE_POSITIONS_SYNC_FLEXQUERY`, `JOB_TYPE_TRADES_SYNC_TWS`, `JOB_TYPE_TRADES_SYNC_FLEXQUERY`).
- In `get_handler`, **remove** the two TWS entries (`JOB_TYPE_POSITIONS_SYNC_TWS: handle_positions_sync_tws` and `JOB_TYPE_TRADES_SYNC_TWS: handle_trades_sync_tws`) from the `handlers` dict.
- **Keep** `handle_positions_sync_tws` and `handle_trades_sync_tws` function definitions, their imports, and any helpers they call. They become unreferenced from `get_handler` but remain in the file for easy reactivation.
- Add a brief inline comment above the `handlers` dict noting that TWS entries are intentionally not registered while Flex Query is the active path. (This is one of the few comments worth writing — the WHY of an absence is non-obvious.)

**Patterns to follow:** Existing `get_handler` dict shape (post-move) in `src/workers/jobs.py`.

**Test scenarios:**
- `get_handler("positions.sync.flexquery")` returns `handle_positions_sync_flexquery` (not `None`).
- `get_handler("trades.sync.flexquery")` returns `handle_trades_sync_flexquery` (not `None`).
- `get_handler("positions.sync.tws")` returns `None` (TWS deactivated).
- `get_handler("trades.sync.tws")` returns `None` (TWS deactivated).
- The old strings (`"positions.sync"`, `"positions.flex_sync"`, `"trades.sync"`, `"trades.flex_sync"`) all return `None` — they are obsolete after U8's backfill.
- The module still imports cleanly (`uv run python -c "from src.workers.jobs import get_handler"`).

**Verification:** A queued `Job` row with `job_type="positions.sync.flexquery"` is claimed and runs through `handle_positions_sync_flexquery` end-to-end against the prod DB; a synthetic `job_type="positions.sync.tws"` row stays in `queued` and is not claimed (or is claimed and immediately fails-out per existing missing-handler behavior — confirm which branch the worker takes today and adjust the assertion accordingly).

---

### U5. Rename service modules to carry explicit `_tws` / `_flexquery` suffixes

**Goal:** Make the TWS vs Flex Query split unambiguous at the services layer as well, so the only place the two share a name is the (unchanged) `Job.job_type` string values.

**Dependencies:** Independent of U1–U4; safest to land after U3 so the worker is already routing only Flex jobs.

**Files (renames):**
- `src/services/trade_sync.py` → `src/services/trade_sync_tws.py`
- `src/services/position_sync.py` → `src/services/position_sync_tws.py`
- `src/services/order_sync.py` → `src/services/order_sync_tws.py`
- `src/services/flex_trade_sync.py` → `src/services/trade_sync_flexquery.py`
- `src/services/flex_position_sync.py` → `src/services/position_sync_flexquery.py`

**Files (importer updates):**
- `scripts/work_jobs.py` — `from src.services.position_sync import (...)` (top of file), `from src.services.order_sync import sync_orders_with_ib` (~line 362), `from src.services.trade_sync import sync_trades_with_ib` (~line 382), `from src.services.flex_trade_sync import (...)` (~line 448), `from src.services.flex_position_sync import sync_flex_positions` and `from src.services.flex_trade_sync import previous_business_day` (~lines 485–486).
- `scripts/download_positions.py` — `from src.services.position_sync import check_positions_tables_ready, sync_positions_once` (~line 14).
- `src/services/trade_sync_flexquery.py` (formerly `flex_trade_sync.py`) — its internal import block at line 28 (currently `from src.services.trade_sync import (...)`) gets split: anything that's a shared helper now lives in `sync_common` (U7) and is imported from there; anything genuinely TWS-specific (if any remains) becomes a `from src.services.trade_sync_tws import (...)`. In practice, after U7 there should be **zero** imports from `trade_sync_tws` here.
- `src/services/position_sync_flexquery.py` (formerly `flex_position_sync.py`) — three import lines change:
  - `from src.services.flex_trade_sync import FlexTokenExpiredError` → `from src.services.trade_sync_flexquery import FlexTokenExpiredError`.
  - `from src.services.position_sync import get_or_create_accounts` → `from src.services.sync_common import get_or_create_accounts` (after U7).
  - `from src.services.trade_sync import _safe_float, _safe_int, _safe_str` → `from src.services.sync_common import _safe_float, _safe_int, _safe_str` (after U7).
- Any test file under `tests/` that imports the five modules — repeat the same swap. Identify with a single grep before editing.

**Approach:**
- Use `git mv` (or the editor's rename) so git tracks the moves cleanly.
- Do all five renames + all importer updates in one commit so the tree never has a half-renamed import graph.
- No function or class bodies change. No public function renames. The Flex modules import shared utilities from `sync_common` (U7), not from the TWS modules.

**Patterns to follow:** Existing module layout under `src/services/`. The renamed modules keep their original public surface; downstream callers only update the import path.

**Test scenarios:**
- `uv run python -c "from src.services.position_sync_tws import check_positions_tables_ready, sync_positions_once, get_or_create_accounts"` succeeds.
- `uv run python -c "from src.services.trade_sync_tws import sync_trades_with_ib, _safe_float, _safe_int, _safe_str"` succeeds.
- `uv run python -c "from src.services.order_sync_tws import sync_orders_with_ib"` succeeds.
- `uv run python -c "from src.services.trade_sync_flexquery import fetch_flex_report, previous_business_day, sync_flex_trades, FlexTokenExpiredError"` succeeds.
- `uv run python -c "from src.services.position_sync_flexquery import sync_flex_positions"` succeeds.
- `uv run python -c "import scripts.work_jobs, scripts.download_positions"` succeeds.
- `rg "from src\\.services\\.(trade_sync|position_sync|order_sync|flex_trade_sync|flex_position_sync)( |$)"` returns zero hits outside `.claude/worktrees/`.
- Existing handler tests for `handle_flex_trades_sync` and `handle_flex_positions_sync` (if present) still pass against the renamed modules.

**Verification:** Full backend test suite passes; an end-to-end Flex Query sync triggered via the UI completes successfully against the prod DB, confirming the renamed Flex services still wire through `scripts/work_jobs.py`.

---

### U7. Extract shared sync helpers into `src/services/sync_common.py`

**Goal:** Eliminate the Flex → TWS cross-imports introduced by U5 by moving the genuinely shared helpers into a neutral module.

**Dependencies:** U5 (or land together with U5 in the same commit, since they touch the same files). Conceptually U7 only makes sense once the renamed module names exist.

**Files (new):**
- `src/services/sync_common.py`

**Files (modified):**
- `src/services/trade_sync_tws.py` (formerly `trade_sync.py`) — remove the bodies of `_safe_float`, `_safe_int`, `_safe_str` (move to `sync_common`). If `trade_sync_tws.py`'s own code uses them, re-import from `sync_common`.
- `src/services/position_sync_tws.py` (formerly `position_sync.py`) — remove the body of `get_or_create_accounts` (move to `sync_common`). If `position_sync_tws.py`'s own code uses it, re-import from `sync_common`.
- `src/services/trade_sync_flexquery.py` — switch its `_safe_float` / `_safe_int` / `_safe_str` import (and anything else moved) to `from src.services.sync_common import ...`.
- `src/services/position_sync_flexquery.py` — switch the helper imports to `from src.services.sync_common import ...`.

**Approach:**
- Create `src/services/sync_common.py`. Move the four helper functions verbatim (no signature changes, no behavior changes): `_safe_float`, `_safe_int`, `_safe_str`, `get_or_create_accounts`.
- For each helper, check whether other callers exist beyond the two sync families (`rg "_safe_float|_safe_int|_safe_str|get_or_create_accounts" src scripts tests`). Update every importer to the new module.
- Helpers stay private-flavored (`_safe_*` keeps its underscore prefix; this is a relocation, not an API change).
- After this unit, `rg "from src\\.services\\.(trade_sync_tws|position_sync_tws) import" src/services/` should return zero hits inside the `*_flexquery.py` files.

**Patterns to follow:** Same package layout as other neutral helper modules under `src/utils/` and `src/services/`.

**Test scenarios:**
- `uv run python -c "from src.services.sync_common import _safe_float, _safe_int, _safe_str, get_or_create_accounts"` succeeds.
- `uv run python -c "from src.services.trade_sync_flexquery import sync_flex_trades, fetch_flex_report"` succeeds (no ImportError chain via `trade_sync_tws`).
- `uv run python -c "from src.services.position_sync_flexquery import sync_flex_positions"` succeeds.
- `rg "from src\\.services\\.(trade_sync_tws|position_sync_tws) import" src/services/trade_sync_flexquery.py src/services/position_sync_flexquery.py` returns zero matches.
- Existing tests that exercise `sync_flex_trades` and `sync_flex_positions` still pass — the helpers behave identically because they were moved verbatim.

**Verification:** End-to-end Flex Query sync (trades + positions) against the prod DB still produces the same row counts and `flex_sync_log` rows it did before the move.

---

### U8. Alembic migration: backfill `jobs.job_type` to the new explicit strings

**Goal:** Bring the persisted job_type strings in line with the new explicit constants so `get_handler()` can resolve historical rows.

**Dependencies:** None at the code level (the migration is data-only), but it must deploy *atomically* with the U1 / U2 / U3 / U6 code changes. See "Deploy sequence" below.

**Files (new):**
- `alembic/versions/<timestamp>_rename_job_type_tws_flexquery.py` (use the existing repo convention; today's prefix would be `20260513...`).

**Approach:**
- Single `upgrade()` function that runs four `UPDATE jobs SET job_type = :new WHERE job_type = :old` statements inside one transaction:
  - `"positions.sync"` → `"positions.sync.tws"`
  - `"positions.flex_sync"` → `"positions.sync.flexquery"`
  - `"trades.sync"` → `"trades.sync.tws"`
  - `"trades.flex_sync"` → `"trades.sync.flexquery"`
- `downgrade()` reverses the four mappings symmetrically.
- Use `op.execute(sa.text(...))` with bound parameters; do not embed user input (there is none, but pattern-match the rest of `alembic/versions/`).
- Add a short docstring at the top of the migration file noting the rename rationale.

**Patterns to follow:** Recent migrations under `alembic/versions/` (e.g., `20260507204422_normalize_side_bot_sld_to_buy_sell.py` is the closest precedent — a value-normalization backfill).

**Test scenarios:**
- After `alembic upgrade head`, every row in `jobs` has `job_type` in the new four-value set; no row retains a legacy string.
- After `alembic downgrade -1`, every row is back to the old four-value set; no row retains a new string.
- A round-trip (`upgrade head` then `downgrade -1` then `upgrade head`) leaves the table identical to its post-first-upgrade state.

**Verification:** Against a snapshot of the prod DB, run the migration in a transactional dry-run (`alembic upgrade head` inside a `BEGIN; ... ROLLBACK;` wrapper) and confirm the expected row counts shifted per the four buckets.

**Deploy sequence (one-line summary):** Stop worker → `alembic upgrade head` → deploy new code → start worker. The migration + code-deploy gap should be measured in seconds; in practice the worker can be stopped, the migration run, the code deployed, and the worker started in one orchestrated step.

---

### U4. Switch frontend trades and positions sync buttons to the Flex Query routes

**Goal:** The UI only kicks off Flex Query syncs.

**Dependencies:** U2.

**Files:**
- `frontend/src/components/PositionsTable.tsx`
- `frontend/src/components/TradesTable.tsx`

**Approach:**
- `PositionsTable.tsx:228`: change `fetch(\`${API_BASE_URL}/positions/sync\`, ...)` to `fetch(\`${API_BASE_URL}/positions/sync/flex-query\`, ...)`. Body remains `{ source, request_text, max_attempts }` — `FlexPositionSyncRequest` accepts the same fields plus optional `account_code` / `start_date` / `end_date` which the UI does not need yet. Update `request_text` to mention "flex query" for log clarity.
- `TradesTable.tsx:591`: change `fetch(\`${API_BASE_URL}/trades/sync\`, ...)` to `fetch(\`${API_BASE_URL}/trades/sync/flex-query\`, ...)`. Drop `lookback_days` from the body (Flex variant uses `days`, defaulting in the handler is fine — or pass `days: lookbackDays`). Adjust `kickOffTradesSync`'s body to send `{ source, request_text, max_attempts, days: lookbackDays }` to match `FlexTradeSyncRequest`.
- No new buttons, no label rewrites beyond updating the `request_text` strings.

**Patterns to follow:** Existing `kickOffPositionSync` / `kickOffTradesSync` functions in the same files.

**Test scenarios:**
- Clicking the positions sync button on `/positions` POSTs to `/positions/sync/flex-query`, gets a 202, and the toast shows `Queued positions sync job #N`.
- Clicking each lookback option on the trades page POSTs to `/trades/sync/flex-query` with the corresponding `days` value, gets a 202, and the toast shows the queued job ID.
- Manual smoke: after kickoff, within ~10s, the worker logs show `handle_flex_*_sync` running and the table refreshes with new data.

**Verification:** Browser network tab confirms the new URLs; worker stdout shows `handle_flex_trades_sync` / `handle_flex_positions_sync` invocation; trades & positions tables refresh post-sync.

---

## System-Wide Impact

- Any external caller (cron, curl, internal script) hitting the old `/trades/sync`, `/trades/flex-sync`, `/positions/sync`, `/positions/flex-sync` paths will 404. Grep before merging:
  - `rg "/trades/sync\b|/positions/sync\b|/trades/flex-sync\b|/positions/flex-sync\b"` across the repo.
- Worktree copies under `.claude/worktrees/*` will diverge — that's expected; they are not in scope here.
- `scripts/work_order_queue.py` and other dispatcher-adjacent scripts also import some of these constants — re-grep `JOB_TYPE_POSITIONS_SYNC\b|JOB_TYPE_TRADES_SYNC\b|JOB_TYPE_FLEX_POSITIONS_SYNC\b|JOB_TYPE_FLEX_TRADES_SYNC\b` and update each non-worktree hit during U1's rename pass.
- The `jobs.job_type` column is unaffected — historical rows continue to resolve.

## Risks & Mitigations

- **Risk:** A consumer (a TWS-only cron, a saved Postman request) silently breaks on the route rename. **Mitigation:** before merging, ripgrep the repo and the deployment config for the four old paths; notify of any remaining call sites.
- **Risk:** TWS handler functions bit-rot once unwired. **Mitigation:** explicit comment in `get_handler` noting why TWS entries are absent; the functions are still typed and importable, so a `uv run python -c "from scripts.work_jobs import handle_trades_sync, handle_positions_sync"` smoke check survives.
- **Risk:** Forgotten reference to the old `JOB_TYPE_*` Python names breaks at import time. **Mitigation:** run the full backend test suite and `uv run python -c "import scripts.work_jobs; from src.api.routers import trades, positions"` before merging.

## Deferred to Follow-Up Work

- Reactivating TWS sync as a real-time data source — separate plan once the use case is concrete.
- A UI-level toggle for "pick a sync source" (TWS vs Flex Query). Not needed while Flex Query is the only active path.
