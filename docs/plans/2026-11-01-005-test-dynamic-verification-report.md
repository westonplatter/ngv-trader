---
title: Dynamic Verification Report - First Run
type: test
date: 2026-11-01
---

# Dynamic Verification Report - First Run

**Scope:** `main` at `e05611d` against baseline `67e99f8` (the tree before the tags/refactor work), same Postgres database, fake data only.
**Method:** real Postgres, real HTTP, real browser (Playwright/Chromium). Two APIs ran side by side on one database (head :8010, baseline :8011); where a build could not share the database (ingest), each got its own fresh one. Baseline UI and head UI were driven by the same scripts.
**Repo state at the end:** clean `main`, no leftover worktree, processes, or databases of mine. The harness scripts and raw results were not committed.

## Verdict: **ship**

I found **no wrong numbers, no data loss, and no crash on a path I could reach**. Every P&L figure, ingested row, and API payload I could compare matched the baseline except for changes that are documented or are fixes. There are three findings worth acting on (F1–F3), one of them in my own feature.

## Findings (most severe first)

The trackable inventory is `docs/plans/2026-11-01-003-fix-post-refactor-verification-findings-plan.md`; F1-F10 below keep the same IDs there, and F11-F13 were added when that plan was written. This section is the as-found record.

### F1. "No strategy" in the group strategy picker makes the group vanish from the Strategies page, with no way back there — *my #319*
- **Repro:** `/strategies?strategy_id=1&trade_group_id=1` → Edit → set Strategy to "No strategy" → Save. The API correctly sets `strategy_id: null`. The page then shows "Select a trade group to view details", and `/strategies?trade_group_id=1` falls back to the first strategy with "No trade groups for this strategy yet."
- **Why:** the page lists groups only under a strategy. The baseline never showed strategy-less groups either, but you couldn't create that state from this page. The option I added is now a one-way door. (Strategy-less groups remain reachable from the Trades page and the API.)
- **Fix options:** drop the "No strategy" option, or add an "Unassigned" entry to the strategy list. Confidence: high (reproduced 3/3).

### F2. A missing contract enqueues a *new* `contracts.sync` job on every lookup — *#348*
- **Repro:** `find_contracts_with_fallback(session, "ZZTEST", "FUT")` twice → jobs #1 and #2, identical payloads, both `queued`. There is no dedupe against an already queued or running job.
- **Why it matters:** the tool text tells the LLM to "check back shortly, then repeat the lookup", so each repeat before the first job finishes adds another TWS job. The baseline fetched synchronously inside the request, so this could not happen there.
- **Not verified:** an unknown FUT root falls back to exchange `SMART` in the enqueued spec; I could not confirm how TWS treats that without a broker.

### F3. An exception after an order reaches a terminal state can now crash the order worker — *#344*
- `process_order`'s `except` handler now uses the enforced transition. If something raises after the order is `filled`/`cancelled`/`rejected`/`failed`, the handler itself raises `ValueError`, and the worker's main loop (`scripts/work_order_queue.py`, around the `process_order` call) has no `try/except`. The batch session is rolled back.
- The baseline used a bare assignment and could not raise, but silently overwrote a *filled* order to `failed`, which is arguably worse.
- Two bypasses of the machine remain: the timeout path (`order_worker.py:356`) and the sync fallback (`order_sync_tws.py:319`).
- **Static analysis only.** I could not run the worker without TWS.

### Lower severity / informational
| # | Finding |
|---|---|
| F4 | Trades realized P&L: a trade with `combo_summary=100`, `leg=70`, `standalone=5` reports **105 on head, 100 on baseline** (#328, documented, pinned by `test_execution_pnl.py`). Trade-group figures are unchanged. Both syncs re-tag standalone siblings of a BAG fill, so this shape is unlikely in real data. |
| F5 | `GET /trade-groups/{id}/executions` now reports `intraday_realized/total` = 30.0 for a group linked only to a combo-summary row (baseline: `null`). Improvement. **Pre-existing on both builds:** that group's list/detail `realized_pnl` and the semantic layer's `realized_pnl` stay `null` while the executions panel says 30.0. |
| F6 | `inserted_executions_count` is **fixed** on head: baseline reported 0 for every Flex run and over-counted on TWS reruns (and `updated_executions_count` was always 0). The three #338 tests called "characterization" fail on baseline for exactly those counters, so they are not pure characterization. Row data is identical (see the #338 row under "What was verified"). |
| F7 | The SSE stream opens twice on page load (`worker_status`, then reopened as `jobs,worker_status`) when the job watcher subscribes. Benign. |
| F8 (plan: F8, F13) | Pre-existing on both builds: the Positions **DTE** header shows `↕` but never sorts; unset `/user-preferences/*` return 404 and appear as console errors on every page. |
| F9 | Unused `datetime` import in `src/api/routers/jobs.py` (from #341). CI doesn't enforce F401. |
| F10 | Cosmetic: closed date `-` → `—`; error wording `HTTP 502:` → `… failed (502)`. |

**Improvement worth knowing about:** the baseline Positions sort had a dead first click and did not restore the original order after a full cycle; head cycles cleanly `↕ → ↑ → ↓ → ↕` (#342).

## What was verified

| Area | Result |
|---|---|
| **A. API black-box** (tag catalog, all 5 entity types, rename/merge/archive, search all/any/none, tasks lifecycle + filters, strategies, hostile input) | **46/46 pass.** One assertion was mine (A7: the default list only fills `realized_pnl` with `include_intraday=true`); corrected and passing. |
| **Concurrency** | 4 × 20-way races plus **8 rounds × 60-way** and a 40-way task+tag create: no 500s, no duplicate rows, no server tracebacks. I cannot prove the requests truly interleaved. |
| **B. Sync paths, real commits** (live→settled carry-over, combo→legs, late-fill inheritance, tag ending + date guard, flat-account sync) | **7/7 pass**, read back through the API. |
| **C. Baseline vs head, same DB** (17 read endpoints incl. intraday and account slices; `compute_trade_group_pnl` for all groups) | **Byte-identical**, with staged live quotes, a second account, and combo rows. Documented changes reproduced: F4, F5. |
| **#338 ingest, full-column diff on fresh DBs** (Flex: 3 syncs incl. extra partial + 3rd revision + rerun; TWS: 4 batches incl. BAG arriving after its legs) | `trades`/`trade_executions` **identical in every column**. Only the counters differ (F6). |
| **D. MCP + semantic layer** | **11/11.** Agent attribution, no rename/merge/archive tools. Dimension is `trade_group` on head (`tag` on baseline) with **identical numbers**; the old name errors with the list of valid dimensions. Tool specs: 14 of 18 identical; the other 4 differ only by #348's descriptions and #318's rename. |
| **E. UI against the real API** (Positions, Trades bulk tagging, Tags page, Tasks, Strategies, Pricing, job watcher) | **32 flows pass.** Highlights below. |
| **Demo mode, 17 routes, baseline vs head** | Same controls and text, no page errors; differences are F10 and a live countdown. Pricing option cascade identical at every step. |
| **Automated suites on `e05611d`** | pytest **541 pass**; frontend **202 pass**; typecheck, lint, build clean; Pyright **80 errors = baseline**; `docs_check` clean; all 6 media images return 200. |

**Job watcher (#331), measured:** stream up + notify delivered → refetch in **75 ms**; stream up + notify **lost** → **7.1 s** (safety net); stream blocked → **1.1 s**. #331's three fixes all survived the later Pricing split.
**Other UI points:** a double-click on a task status sends **one** PATCH; a failed structure delete shows "Delete failed" and keeps it selected; "follow the group" after changing strategy works; the type-ahead correctly hides tags already on the item.

## Could not verify
- Anything needing TWS/IBKR: the order worker end to end, the intraday TWS sync, the `contracts.sync` handler, real Flex fetches (F3 and F2's SMART point stay unconfirmed).
- The external pricing service behind `/pricing-api` (Calculate PnL returns 502 on both builds here), and the leg price-fetch via the watcher.
- Alembic downgrade paths; multi-client SSE behavior.
- Many of my first-pass UI failures were my own harness (assertions that didn't wait, selectors, state left by earlier steps). I diagnosed each before reporting; none were product bugs, and the corrected runs are the numbers above.
