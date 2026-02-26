# Plan: Changes To Manually Test

## Backend Changes

- Added shared order mutation service at `src/services/order_mutations.py`:
  - New `OrderCreateInput` and `OrderCreateOutcome` dataclasses.
  - New normalization/validation for order fields.
  - New idempotent create matcher including `limit_price`.
  - New `create_queued_order(...)` that writes `order_created` event and returns `created=True/False`.

- Updated Orders API create flow at `src/api/routers/orders.py`:
  - `OrderCreateRequest` now includes `limit_price`.
  - Replaced inline create/idempotency logic with shared `create_queued_order(...)`.
  - Keeps API behavior: `201` for created, `200` for idempotent match.
  - Removed now-unused inline idempotency constants/helper.

- Updated Tradebot agent at `src/services/tradebot_agent.py`:
  - System prompt changed from execution-disabled to execution-capable.
  - Added tool specs and handlers for:
    - `preview_order` (validate/normalize only; no DB write)
    - `submit_order` (queues order via shared mutation service)
  - Added account resolution by `account_id` or `account` alias/account number.
  - Added shared arg parsing for symbol/side/qty/sec_type/exchange/currency/order_type/limit_price/tif.
  - Added validation-safe error paths via existing tool error handling.

- Updated order worker execution at `scripts/work_order_queue.py`:
  - Added `LimitOrder` import.
  - Submission logic now:
    - `LMT` -> `LimitOrder(side, qty, limit_price)` (fails if missing price)
    - otherwise -> `MarketOrder(side, qty)`

## Docs Changes

- Updated restore spec at `docs/spec-restore-order-fetching-and-submission.md`:
  - Marked PR 5 as implemented.
  - Documented restored `preview_order`/`submit_order`.
  - Documented shared mutation service and worker LMT support.

- Updated chatbot docs at `docs/tradebot-chatbot.md`:
  - Replaced “execution disabled/read-only” language.
  - Added `preview_order` and `submit_order` to action tools.
  - Clarified cancel is via Orders API/UI (not chat tool).

- Updated LangGraph implementation docs at `docs/tradebot-langgraph-implementation.md`:
  - Replaced non-execution posture with restored execution posture.
  - Added `preview_order` and `submit_order` to tool surface.
  - Clarified submit queues orders; broker submission remains worker-based.

- Updated docs index at `docs/_index.md`:
  - Updated descriptions/tags to reflect execution-capable Tradebot and PR5 status in restore spec.

## Validation Status

- Ruff: passed on changed Python files.
- Pyright: passed on changed Python files.
- `scripts/check.py`: failed in current env due missing dependency `typer`.
