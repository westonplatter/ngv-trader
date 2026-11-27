---
title: Backend Python anti-pattern cleanup - Plan
type: refactor
date: 2026-11-27
---

# Backend Python anti-pattern cleanup - Plan

**Status:** NOT STARTED. Lite plan: it records findings from one review pass of `src/`.
Line numbers and counts are from 2026-11-27 and are not re-verified here.
**Source:** a dignified-python review of `src/` (94 files, about 22k lines).
**Scope:** 12 findings, in three priority tiers. Each item can ship as its own PR.

## What is already good

No relative imports, no `os.path`, no `Optional`/`List` typing, no bare `except:`, no
`print`, no f-string logging, and no mutable default arguments. Do not churn these.

## High

### 1. Swallowed IBKR errors in order sync

- `src/services/order_sync_tws.py:102-125`: three `except Exception` blocks `pass` or
  reset the result to `[]` around `reqAutoOpenOrders`, `reqAllOpenOrders`, and
  `reqCompletedOrders`. Nothing is logged.
- Risk: order sync reports success but has silently dropped orders.
- Fix: catch the narrowest ib_async/connection error, call `logger.exception` with
  the call name, and keep the fallback. Follow `src/services/intraday_sync_tws.py:173`,
  which already does this.
- Smallest, highest-value item. Do it first.

### 2. `getattr` duck typing on typed objects (214 calls)

- Concentrated in `trade_sync_tws.py` (46), `order_sync_tws.py` (45),
  `intraday_sync_tws.py` (38), and `market_data.py` (22).
- Example: `_fill_to_raw(fill: Any)` in `src/services/trade_sync_tws.py:36` reads
  `Fill`/`Execution` fields with `getattr(x, "field", None)`. A typo becomes `None`, and
  Pyright cannot catch it.
- Fix: type the parameters as the ib_async classes (`Fill`, `Execution`, `Trade`,
  `Ticker`), then use attribute access. For a real union, narrow it with `isinstance`,
  e.g. `src/api/routers/watch_lists.py:113-123` on
  `LatestFuturesOptions | LatestFutures`.
- Do it file by file when already editing the sync code. Coordinate with the ib_async
  v3 upgrade (`docs/plans/2026-11-19-001-chore-ib-async-v3-upgrade-plan.md`), which
  touches the same fields.

### 3. Untyped job payloads

- `src/workers/jobs.py`: handlers do `payload = job.payload or {}` and then
  `payload.get(...)` (53 calls). 25 handlers return a bare `-> dict`. There are 118
  `dict[str, Any]` across `src/`.
- Fix: add one Pydantic model per job type. Validate it at enqueue
  (`src/services/jobs.py`) and parse it at the start of each handler. Give each handler
  a typed result model, or a `TypedDict` where the result is stored as JSON.
- Do this after item 4, so the payload models can hold a `TwsConnection`.

## Medium

### 4. Repeated TWS connect code, and `TwsConnection`

- `ib.connect(host, port, clientId=..., timeout=...)` appears 10 times across 8
  modules: `contract_sync`, `market_data`, `order_sync_tws`, `position_sync_tws`,
  `trade_sync_tws`, `watchlist_instrument_sync`, `watchlist_quotes`, and
  `workers/jobs.py`.
- `resolve_tws_connection` in `src/workers/jobs.py:115` returns a bare 4-tuple.
- Fix (directional):

  ```python
  @dataclass(frozen=True)
  class TwsConnection:
      host: str
      port: int
      client_id: int
      connect_timeout_seconds: float = 20.0

      @classmethod
      def from_payload(cls, payload: dict, *, default_client_id: int) -> "TwsConnection": ...
  ```

  Add a `connect_ib(conn)` context manager. Services take `conn: TwsConnection` (or an
  `IB` from the existing `IBSessionPool` in `src/workers/jobs.py:64`), not four
  separate parameters.

- This also removes about 8 of the 26 `noqa: PLR0913` (item 11).

### 5. Imports inside functions without a reason (about 40)

- `src/workers/jobs.py:147-773` imports inside nearly every handler, including names
  that are already imported at the top (`src.services.jobs`).
- `src/api/routers/futures.py` imports `timedelta`, `func`, `aliased`, `math`,
  `OptionChainMeta`, `LatestFutures`, and `option_filters` inside functions, and imports
  `math` twice (lines 421 and 425).
- These imports do not avoid a cycle: nothing in `src/services`, `src/api`, or
  `src/models.py` imports `src.workers`.
- Fix: move all of them to the top of the file, and merge them into the existing
  `src.services.jobs` import block. If one move raises an import error, that is a real
  cycle. Break the dependency, or keep only that one import inside the function with a
  one-line comment that says why.
- Guard: enable Ruff `PLC0415` so new imports inside functions fail lint.
- Verify: `uv run python scripts/check.py src.workers.jobs` and Ruff.

### 6. Routers hold domain logic

- `src/api/routers/trade_groups.py` (1,513 lines, 31 queries, 9 commits) and
  `src/api/routers/trades.py` (953 lines, 24 queries).
- `src/api/routers/futures.py` opens `Session(get_engine())` 5 times. All other
  routers use `Depends(get_db)`.
- Fix: switch `futures.py` to `Depends(get_db)` now (small). Move query and mutation
  logic from the large routers into `src/services/` when a feature next touches them.
  Do not do a big-bang move.

### 7. Date math that depends on the server time zone

- `date.today()` / `datetime.now()` are used for DTE and expiry math in
  `src/api/routers/futures.py`, `src/api/routers/structures.py:43`,
  `src/services/market_data.py:341`, `src/services/execution_display.py:48`, and
  `src/services/trade_sync_flexquery.py:48`.
- Risk: DTE filters are off by one day near midnight.
- Fix: one helper that gives "today" in an explicit time zone (exchange time, or UTC
  where that is the intent). Replace the calls. Add tests that pin the clock near
  midnight.

## Low

### 8. Re-export `__init__.py` files

- `src/api/routers/__init__.py` and `src/services/semantic/__init__.py` re-export with
  `__all__`, so each symbol has two import paths.
- Fix: import from the canonical module and empty the `__init__.py` files.

### 9. `global` cache in crypto

- `src/utils/crypto.py:52,71` uses `global _cached_fernet`.
- Fix: `@cache` on `_get_fernet`, and `reset_cache()` calls `_get_fernet.cache_clear()`.
  This matches `src/db.py:19`.

### 10. Side effects at import time

- `src/api/main.py:40-41` reads `ENV` and runs `load_dotenv` at import.
- `src/services/tradebot_agent.py:87` and `src/services/worker_heartbeat.py:27` read
  environment variables into module constants.
- `src/db.py` reads `os.environ` directly instead of `src/utils/env_vars.py`.
- Fix: read config in a function or at app startup, and route through `env_vars`.

### 11. Ruff suppressions instead of refactors

- 26 `noqa: PLR0913` and 10 `noqa: C901`, most added in #353. Three groups:
  1. **TWS connection fields (about 8).** Item 4 fixes these.
  2. **Filter/spec bundles (about 10).** `contract_lookup.find_contracts` /
     `select_contract`, `contract_sync._upsert_contract` (`spec_*` fields), and
     `futures._build_options_query`. Group each set into a frozen dataclass
     (`ContractFilter`, `ContractSpec`).
  3. **FastAPI routes (about 6).** Many parameters are normal for a route. Keep the
     suppression, or add a per-file ignore for `src/api/routers/*`. Use a Pydantic query
     model (`Annotated[Model, Query()]`) only where a filter set is reused.
- Look at the `C901` functions when you next edit each one. No dedicated pass.

### 12. Tradebot returns error strings

- `src/api/routers/tradebot.py:61`: any exception becomes HTTP 200 with
  `"Tradebot error: <raw exception>"` as the chat reply. Nothing is logged, and SQL or
  driver text can leak to the UI. `except ValueError` is too broad for the 400 case.
  - Fix: add a `TradebotConfigError` and map it to `HTTPException(400)`. Remove the
    broad catch, so FastAPI's 500 handler logs the error and hides the details.
- `src/services/tradebot_agent.py:1240`: catching here is correct, because a tool
  failure must not end the chat loop. But the raw `str(exc)` goes to the LLM, and
  nothing is logged.
  - Fix: add a `ToolError` whose message is safe to show. Return its text. For any
    other exception, call `logger.exception` and return a generic
    `"Tool '<name>' failed with an internal error."`.
  - Keep the `_ToolArgsError` path at line 1236 as is.

## Order of work

1. Item 1 (swallowed order-sync errors).
2. Item 12 (tradebot errors) and item 5 (imports). Both are small and mechanical.
3. Item 4 (`TwsConnection` + `connect_ib`), which clears part of item 11.
4. Item 3 (typed job payloads), built on item 4.
5. Item 7 (date helper).
6. Items 8, 9, 10, the `futures.py` part of item 6, and item 11 group 2, as small PRs.
7. Item 2 and the rest of item 6: do them as you touch the code. Line up item 2 with the
   ib_async v3 upgrade.

## Verification (per PR)

`uv run python scripts/check.py`, Ruff, Pyright, and `task test`. For items 1, 7, and
12, add tests that cover the new behavior: the logged fallback, a clock near midnight,
and the tool or route error shape.
