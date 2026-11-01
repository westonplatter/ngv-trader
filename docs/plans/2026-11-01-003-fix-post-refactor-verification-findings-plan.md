---
title: Post-Refactor Verification Findings - Plan
type: fix
date: 2026-11-01
execution: code
---

# Post-Refactor Verification Findings - Plan

## Goal Capsule

- **Objective:** Track every unexpected behavior and open question found by the first dynamic verification run, and resolve them one at a time.
- **How to use it:** Each item (F1, F2, ...) is independent unless it names a dependency. One item per PR. A different agent session can own each one.
- **Authority:** The item's _Expected_ line is the target. Items marked **Decision** need a human answer before any code. Do not widen an item's scope.
- **Stop conditions:** Stop and ask if the fix would change an API response shape, a migration, or behavior another item covers.
- **Execution profile:** Code and tests per item. No schema changes unless the item says so (then follow `docs/contributing/database-migrations.md`).

## Working an item

1. Read the item. Reproduce it with the verification steps it names (IDs like `A1`, `C2`, `E5` refer to the dynamic verification handoff (`docs/plans/2026-11-01-004-test-dynamic-verification-handoff-plan.md`, a sibling PR)).
2. Write the failing test first. Prefer the narrowest level that shows the bug.
3. Fix. Re-run the item's listed steps and the full suites (`task test`, `bun run typecheck && bun run lint && bun test && bun run build`).
4. In the same PR, tick the item's **Status** box, link the PR in the [Resolution log](#resolution-log), and keep the doc's other items untouched.
5. If the item turns out not to be a bug, record why in its **Notes** and close it the same way.

## Run context

- Verified: `main` at `e05611d` against baseline `67e99f8` (the tree before tags/tasks), on one Postgres database, fake data only.
- Method: head and baseline APIs side by side; Playwright against the real API; separate fresh databases for the ingest comparison. Raw scripts and results were kept by the verifier, not committed.
- Results that matched the baseline are not repeated here: 17 read endpoints byte-identical, trade-group P&L service identical, Flex and TWS ingest identical in every column, semantic-layer numbers identical, 46 API checks and 32 UI flows passing.
- Automated suites at that commit: pytest 541, frontend 202, Pyright 80 errors (all pre-existing, same as baseline).

## Inventory

| ID  | Severity | Kind                | Area                      | Title                                                        | Status |
| --- | -------- | ------------------- | ------------------------- | ------------------------------------------------------------ | ------ |
| F1  | Medium   | Gap, **Decision**   | Strategies page           | "No strategy" makes a group vanish from the page             | [ ]    |
| F2  | Medium   | Bug                 | Contract lookup           | Every lookup miss queues another `contracts.sync` job        | [ ]    |
| F3  | Medium   | Bug (risk)          | Order worker              | Exception after a terminal state can crash the worker        | [ ]    |
| F4  | Medium   | **Decision**        | Trades P&L                | Realized rule now adds standalone rows next to a combo summary | [ ]  |
| F5  | Low      | Bug (pre-existing)  | Trade-group P&L           | Combo-only group: realized is `null` in some views, 30 in others | [ ] |
| F6  | Low      | Test/doc            | Trade-sync tests          | "Characterization" tests pin changed counters                | [ ]    |
| F7  | Low      | Behavior            | SSE client                | Stream opens twice on page load                              | [ ]    |
| F8  | Low      | Bug (pre-existing)  | Positions table           | DTE header never sorts                                       | [ ]    |
| F9  | Trivial  | Lint                | Jobs router               | Unused import not caught by CI                               | [ ]    |
| F10 | Trivial  | Cosmetic            | Frontend text             | Changed glyph and error wording                              | [ ]    |
| F11 | Low      | **Decision**        | Tags                      | Archived tags keep showing as chips on items                 | [ ]    |
| F12 | Low      | UX                  | Positions table           | Many tags stack vertically and make rows very tall           | [ ]    |
| F13 | Trivial  | Noise (pre-existing)| User preferences          | Unset preferences log a 404 console error on every page      | [ ]    |
| V1-V9 | n/a    | Verification gap    | see [Not yet verified](#not-yet-verified) | Areas the first run did not reach                | [ ]    |

## Items

### F1. "No strategy" makes a group vanish from the Strategies page

- **Status:** [ ] open. **Kind:** gap. **Needs decision:** yes. **Origin:** #319 (strategy picker), page split in #335.
- **Where:** `frontend/src/components/strategies/GroupEditForm.tsx` (the `No strategy` option), `StrategiesPage.tsx` (`saveGroup`, the `else` branch that reloads), `useTradeGroups.ts` (lists groups per strategy).
- **Observed:** Edit a group, choose "No strategy", Save. The API correctly sets `strategy_id: null`. The page then shows "Select a trade group to view details". Opening `/strategies?trade_group_id=<id>` falls back to the first strategy with "No trade groups for this strategy yet." There is no way back to that group on this page. Reproduced 3 of 3 times.
- **Expected:** Either a group cannot be orphaned from the page it was just edited on, or it stays findable.
- **Baseline:** the page never showed strategy-less groups, but its UI could not create that state.
- **Options:** (a) remove the "No strategy" option from the edit form; (b) add an "Unassigned" entry to the strategy list so strategy-less groups have a home; (c) keep it and show a toast linking to the Trades page. Recommend (a) unless unassigned groups should be editable here.
- **Verify with:** `E5` (change strategy to Calendar, clear it, restore it; edit notes only).
- **Notes:** the API already treats `null` as "clear" and omitted as "leave", so no backend change is needed.

### F2. Every lookup miss queues another `contracts.sync` job

- **Status:** [ ] open. **Kind:** bug. **Origin:** #348.
- **Where:** `src/services/contract_lookup.py`, `find_contracts_with_fallback` (the `enqueue_job` call) and `_sync_spec`; tradebot tools `lookup_contract` and `add_watch_list_instrument` in `src/services/tradebot_agent.py`.
- **Observed:** Looking up the same missing symbol twice created two `queued` jobs with identical payloads. The tool text tells the LLM to "check back shortly, then repeat the lookup", so each repeat before the first job finishes adds another TWS job.
- **Expected:** One queued or running `contracts.sync` per symbol and security type; a repeat returns the existing job id as `pending_job_id`.
- **Baseline:** fetched synchronously inside the request, so duplicates could not occur.
- **Suggested fix:** reuse an existing job with the same `job_type` and payload spec that is `queued`/`running` (the repo has `enqueue_job_if_idle`; check whether it fits or whether the payload needs to be part of the match).
- **Also check:** an unknown FUT root falls back to exchange `SMART` in the spec (`_sync_spec`), and `handle_contracts_sync` in `src/workers/jobs.py` passes that to `Future(...)`. Confirm with TWS (or a fake) that this is acceptable; if not, fail the lookup instead of queuing it.
- **Verify with:** `B7`.

### F3. An exception after a terminal state can crash the order worker

- **Status:** [ ] open. **Kind:** bug (risk, static analysis). **Origin:** #344.
- **Where:** `src/services/order_worker.py` (`process_order`, the `except Exception` handler near the end), `scripts/work_order_queue.py` (the loop that calls `process_order` has no `try/except`).
- **Observed:** The handler now calls the enforced `transition_order_status(..., FAILED)`. From `filled`, `cancelled`, `rejected`, or `failed` that raises `ValueError`, which escapes `process_order` and the worker loop; the batch session rolls back. The baseline used a bare assignment, which never raised but silently overwrote a filled order to `failed`.
- **Expected:** An error after a terminal state is recorded without changing that state, and never takes the worker down.
- **Also found:** two writers still bypass the state machine: the timeout path (`order.status = ORDER_STATUS_FAILED` in `order_worker.py`) and the sync fallback (`order.status = normalized_status` in `src/services/order_sync_tws.py`). Decide whether they should use `force=True` or the checked path, then make them consistent.
- **Not reproduced:** needs a fake IB. `tests/test_order_worker.py` shows the pattern; add a case where the handler runs against a terminal order.
- **Verify with:** `B7` (status-write map and transition table), plus the new test.

### F4. Realized rule now adds standalone rows next to a combo summary

- **Status:** [ ] open. **Kind:** behavior change. **Needs decision:** yes (confirm intended). **Origin:** #328.
- **Where:** `src/services/execution_pnl.py` (`realized_pnl_total`), used by `src/api/routers/trades.py`.
- **Observed:** A trade with rows `combo_summary=100`, `leg=70`, `standalone=5` reports **105**; the baseline reported **100**. Trade-group figures are unchanged. `tests/test_execution_pnl.py` pins 105.
- **Reachability:** low. Both syncs re-tag standalone siblings of a BAG fill to `leg`.
- **Decision:** is 105 the intended rule? If yes, close with a note. If no, restore combo-summary-only for trades and keep the group rule.
- **Verify with:** `C1` (staged mixed-role trade; compare `/trades` on baseline and head).

### F5. Combo-only group: realized is `null` in some views and 30 in others

- **Status:** [ ] open. **Kind:** bug (pre-existing on both builds).
- **Where:** `src/api/routers/trade_groups.py` (list and detail realized), `src/services/trade_group_pnl.py`, `GET /trade-groups/{id}/executions`, and the semantic layer's `realized_pnl`.
- **Observed:** For a group linked only to a Flex combo-summary row with no `con_id` and a realized value of 30: `GET /trade-groups` and `/{id}` report `realized_pnl: null`; `GET /trade-groups/{id}/executions` reports `total_realized_pnl: 30` (and since #328 `intraday_realized_pnl: 30`, which was `null` before); the semantic layer reports `null` for that group.
- **Expected:** One number per group across views.
- **Suggested fix:** decide whether the list/detail realized should include rows with no `con_id` (the position-pair collection skips them), then align the three paths and add a test.
- **Verify with:** `C1`, `C3`, `D2`.

### F6. "Characterization" tests pin counters that changed

- **Status:** [ ] open. **Kind:** test/doc. **Origin:** #338.
- **Where:** `tests/test_trade_sync_flexquery.py`, `tests/test_trade_sync_tws.py` (module docstrings).
- **Observed:** Run against the pre-refactor code, three tests fail, all on counters: baseline reported `inserted_executions_count` of 0 for every Flex run, over-counted it on TWS reruns, and always reported `updated_executions_count` as 0. Head reports the true numbers. Row data is identical in every column across multiple batches.
- **Expected:** The docstrings say which assertions are true characterization and which pin a deliberate correction.
- **Suggested fix:** note the corrected counters in the docstrings and in `docs/design/trades-and-executions-sync.md` if it describes them. No code change.
- **Verify with:** `C2`.

### F7. The SSE stream opens twice on page load

- **Status:** [ ] open. **Kind:** behavior. **Origin:** #325, #331.
- **Where:** `frontend/src/lib/events.ts` (the topic list in the stream URL), `frontend/src/hooks/useJobWatcher.ts` (subscribes to `jobs` after mount).
- **Observed:** A page first opens `events/stream?topics=worker_status`, then reopens as `topics=jobs,worker_status` when a job watcher mounts. Functionally harmless; the watch's initial read covers the gap.
- **Expected:** One connection per page, or a documented reason for the reopen.
- **Suggested fix:** subscribe to all topics a page needs before the first connect, or keep one stream and add topics without reconnecting.
- **Verify with:** `E7` (job watcher latencies must not regress: notify 75 ms, lost notify about 7 s, stream blocked about 1 s).

### F8. DTE header never sorts

- **Status:** [ ] open. **Kind:** bug (pre-existing; seen in demo mode on baseline and head).
- **Where:** `frontend/src/components/positions/columns.ts`, `PositionsTableBody.tsx`, `frontend/src/lib/positions/view.ts`.
- **Observed:** The DTE header shows `↕` and clicking it changes neither the arrow nor the order, across four clicks. Other sortable headers cycle correctly.
- **Expected:** DTE sorts ascending, descending, then back, like Expiry.
- **Notes:** `view.ts` lists `dte` as a sort key and has a unit test for it, so check how the header decides it is sortable. Confirm against real rows too (demo data has few distinct values).
- **Verify with:** `E8`.

### F9. Unused import not caught by CI

- **Status:** [ ] open. **Kind:** lint. **Origin:** #341.
- **Where:** `src/api/routers/jobs.py` line 3 (`from datetime import datetime`).
- **Observed:** `ruff check --select F401,F821 src` reports it. CI runs Ruff but `pyproject.toml` selects only complexity rules, so this class of finding is never enforced.
- **Expected:** Remove the import. Optionally add `F401` and `F821` to the Ruff `select` list in the same PR if the rest of `src` is clean.
- **Verify with:** `F` (lint step).

### F10. Changed glyph and error wording

- **Status:** [ ] open. **Kind:** cosmetic. **Needs decision:** only if the wording matters.
- **Observed:** A null closed date renders `—` (was `-`). Shared-client errors read `... failed (502)` (was `HTTP 502:`). The shared client also drops the old `<detail> (<status>)` form.
- **Expected:** Consistent wording across pages. Close with a note if this is acceptable.

### F11. Archived tags keep showing as chips on items

- **Status:** [ ] open. **Kind:** behavior. **Needs decision:** yes. **Origin:** #313.
- **Where:** `src/api/routers/tags.py` (archive endpoint), `src/services/item_descriptions.py` (`tags_by_item`), `docs/design/tags-and-tasks.md`.
- **Observed:** After `POST /tags/{id}/archive`, the tag disappears from `GET /tags` (unless `include_archived=true`) but its chips still appear on items in `/trade-executions`, `/positions`, and `/trade-groups`, and in search results.
- **Decision:** should archiving also hide the chips and exclude the tag from search? If chips stay, say so in the design doc. If they go, filter archived tags in `tags_by_item` and `search_by_tags` and add a test.
- **Verify with:** `A11`, `A12`.

### F12. Many tags stack vertically and make rows very tall

- **Status:** [ ] open. **Kind:** UX.
- **Where:** the Tags cell in `frontend/src/components/positions/` (and the same chip layout on Trades).
- **Observed:** With about ten chips on one position the row grew to roughly ten chip-heights because chips wrap one per line in a narrow column.
- **Expected:** Chips wrap horizontally and the cell caps its height (for example "+3 more").
- **Verify with:** `E1`.

### F13. Unset preferences log a 404 console error on every page

- **Status:** [ ] open. **Kind:** noise (pre-existing on both builds).
- **Where:** `GET /user-preferences/{key}` in `src/api/routers/user_preferences.py`; callers `privacy_mode` and `trade_tagging_focus_mode`.
- **Observed:** A missing preference returns 404, the client handles it, and the browser logs `Failed to load resource ... 404` on every navigation.
- **Expected:** Return a default or 204 for unset keys, or accept the noise and close.

## Not yet verified

These were merged after the first run's commit or could not be exercised. Each is a verification task, not a known bug.

| ID  | Area                                              | What to run                                                                                          |
| --- | ------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| V1  | #355 Tags page split into hooks, lib, and panes   | `E3` (search tabs, URL state, rename, archive, merge) on the real API                                 |
| V2  | #356 Strategy P&L table split                     | `E8` (sort, privacy) and a demo-mode route comparison against baseline                                |
| V3  | #357 trade-group picker driven from state         | `E2` (Trades assign flow) and the type-ahead cases in `E1`                                            |
| V4  | #353 Ruff complexity cleanup across 24 files      | Full `A`, `B`, `C`, `D` plus both test suites; this refactor touched many files with no behavior note |
| V5  | #350, #351 (`now_utc` moved to `src/utils/time`)  | grep for stragglers; run `A13` (completed_at) and the job and order timestamp paths                   |
| V6  | Anything that needs TWS                           | Order worker end to end with a fake IB (F3), `contracts.sync` handler (F2), intraday TWS sync          |
| V7  | Migrations                                        | `alembic downgrade` and re-upgrade for the tag and strategy migrations on a seeded database           |
| V8  | Multi-client SSE                                  | Two browsers, one notify; confirm both refresh and neither misses a terminal state                    |
| V9  | Pricing service behind `/pricing-api`             | `Calculate PnL` with the service running (it returned 502 on both builds without it); leg price fetch |

## Resolution log

| ID  | PR  | Outcome |
| --- | --- | ------- |
|     |     |         |
