---
title: Dynamic Verification Handoff - Plan
type: test
date: 2026-11-01
execution: code
---

# Dynamic Verification Handoff - Plan

## Goal Capsule

- **Objective:** Find out whether the tags/tasks work and the refactors after it actually work when run (real Postgres, real HTTP, real browser, committed transactions) and whether anything regressed against the code before it.
- **Means:** Six lettered parts, A to F, run against a throwaway database and a baseline worktree. Teams can split the work by letter.
- **Authority:** The verifier reports and does not fix. No code changes, no PRs, no pushes. If unsure whether something is a bug, report it as a question with evidence.
- **Stop conditions:** Stop and report if the throwaway database cannot be isolated from `dev`/`prod`, if a scenario would need real IBKR data, or if a step would change git state beyond a baseline worktree.
- **Execution profile:** Dynamic checks only. Fake data only. Output is one markdown report in the format at the end.

Read `AGENTS.md` first and obey it. The rules that matter here:

- **Fake data only.** Never use or commit real IBKR account IDs, conids, or exec IDs. The fake ones (`U1234567`, conids `1000000001..3`, exec ids `0000abcd.…`) come only from `tests/trade_group_factories.py`.
- **Throwaway database only.** Never point anything at the `dev`/`prod` databases or read `.env.dev`/`.env.prod`. Do not use `op`/1Password. Everything below runs against a database you create called `ngv_verify`. Schema comes only from Alembic. Writing rows directly into `ngv_verify` to stage a scenario is allowed (it is a disposable fixture); doing so anywhere else is not.
- **Do not touch git state** beyond reading it. Do not push to `main` or the `media` branch. If you create a worktree for the baseline, remove it when done.
- Python via `uv run python`. Clean up background processes you start.

## Known findings to confirm or close

[The findings plan](2026-11-01-003-fix-post-refactor-verification-findings-plan.md) inventories the issues the first verification run found; [the first-run report](2026-11-01-005-test-dynamic-verification-report.md) is the evidence behind it. Read it first. Re-test those items (confirm fixed, or confirm still present) instead of rediscovering them.

## What was built (so you know what "correct" means)

Read `docs/design/tags-and-tasks.md` end to end; it is the spec. In short:

- **Tags** are free-form labels on trades, live (unsettled) fills, positions, trade groups, and tasks. **Tasks** are to-dos (`todo`/`in_progress`/`done`) linked to strategies, groups, positions, trades. REST: `/tags`, `/tag-links`, `/tags/search`, `/tasks`. MCP tools wrap the REST API (`src/mcp/semantic_server.py`).
- Items are keyed by **typed keys**: trade id; `(account_id, con_id)` for a position; `ib_exec_id` for a live fill. Tagging one live fill **fans out** to every live fill of its order (same `permId`, else `orderId`).
- Links must **survive sync**: live fill → settled trade (carry-over), late partial fills inherit, and a position tag **ends** (`ended_at`) once the contract is flat in settled and live data and the settled snapshot date is not older than the tag.
- **Strategies** left the tag tables (own `strategies` table, `trade_groups.strategy_id`). Old params are rejected loudly, not ignored.
- Merged afterwards: Ruff line-length pin (#323); shared API schemas / `item_links` split / router-import cleanup (#321, #322, #327); a frontend API client, SSE and job-watcher hooks (#324–#326, #331); a P&L overlay facade (#328); and four page splits that had not been reviewed at all: #329, #332 (Trades), #335 (Strategies), #336 (Pricing). Weight your time toward those.

## What changed since

The original set was #312–#336. After it, these also merged and need coverage:

| PR | Change |
| --- | --- |
| #337 | Lazy-load the pricing page |
| #338 | One fill ingest behind the FlexQuery and TWS trade syncs |
| #339 | `StrEnum` vocabularies |
| #340 | Option selector hooks, FOP spec |
| #341 | Order group key; response schemas moved out of routers |
| #342 | Shared table sort |
| #343 | Entity-type registry |
| #344 | Order state machine; worker policy service |
| #347 | Tradebot tool registry |
| #348 | Contract lookup enqueues a job instead of calling TWS |
| #349 | Money/quantity masking hook |
| #350 | Hoist the repeated bordered-button classes (frontend) |
| #351 | `now_utc` defined once in `src/utils/time` |
| #353 | Ruff complexity cleanup across many files |
| #355 | Tags page split |
| #356 | Strategy P&L table split |
| #357 | Trade-group picker |

**Coverage by the first run.** It exercised the #312–#349 behavior listed in this document, plus the job watcher (#331), and the ingest (C2), order and contract (B7), tradebot (D3), and semantic checks described below. It did **not** reach #350, #351, #353, #355, #356, #357. Prioritize those: the Tags page split (#355) in E3; the Strategy P&L table split (#356) in E8 (sort and privacy) and F1 (demo routes); the trade-group picker (#357) in E1 and E2 (the `+ Assign` flow); `now_utc` (#351) by grepping for stragglers and re-running A13 (`completed_at`) and the job and order timestamp paths; and the complexity cleanup (#353) through the full A to D steps, the C differentials, and the F static checks.

## 1. Setup

Postgres 16 is local to the container: `pg_ctlcluster 16 main start` (user `postgres`, password `postgres`). It stops between turns; restart it if connections are refused.

```bash
cd /path/to/ngv-trader && git checkout main && git pull
export DB_HOST=localhost DB_PORT=5432 DB_USER=postgres DB_PASSWORD=postgres DB_NAME=ngv_verify ENV=verify
PGPASSWORD=postgres dropdb -h localhost -U postgres --if-exists ngv_verify
PGPASSWORD=postgres createdb -h localhost -U postgres ngv_verify
uv run alembic upgrade head          # ENV=verify points at no .env file on purpose
```

**Seed** with the script in the [Appendix](#appendix-seed_verifypy) (`seed_verify.py`; copy it to the repo root, run `uv run python seed_verify.py`, then delete the copy so the tree stays clean). It creates: account `U1234567`; strategies `Wheel` (id 1) and `Calendar` (2); groups `CL roll` (1, Wheel), `NG spread` (2), `ES hedge` (3); four settled fills; settled positions for CL and NG; a live-only ES position; and **two live fills of one order** (`…00000101…`, `…00000102…`, same `permId`) for fan-out.

**Run the API** (CORS only allows the origin `http://localhost:5173`):

```bash
uv run uvicorn src.api.main:app --port 8010 > /tmp/api8010.log 2>&1 &
curl -s localhost:8010/api/v1/health      # {"status":"ok","database":"connected"}
```

**Baseline** (the code before the tags/refactor work, commit `67e99f8`; the schema is identical, so it runs on the *same* database):

```bash
git worktree add /tmp/ngv-base 67e99f8
cd /tmp/ngv-base && uv sync --group dev && uv run uvicorn src.api.main:app --port 8011 &
```

Run `git worktree remove --force /tmp/ngv-base` at the end.

Test env for pytest: write a temp `.env.testlocal` with the `DB_*` values above and `DB_NAME=ngv_trader_test`, then `TEST_ENV_FILE=.env.testlocal uv run --extra mcp pytest -q`. Delete the file afterwards. Reference counts on current `main`: full pytest suite 541 tests, frontend suite 202 tests.

## Gotchas learned in the first run

These cost real time. Avoid them.

- Never `pkill -f <pattern>` or `ps | grep | xargs kill` when the pattern is also in your own command line: it kills your shell. Match on PIDs from `ps -eo pid,args | awk`, excluding `awk` and `bash`.
- Never use Playwright `networkidle`: the SSE stream holds a connection open forever. Use `load` plus explicit polling.
- Never assert immediately after an action: poll (`until`) for the API or DOM state. Playwright `isVisible()` does not wait, and `check()` can fail on React-controlled checkboxes; use `click()` then poll `isChecked()`.
- A route registered later in Playwright overrides an earlier one: re-registering a pass-through route silently undoes an abort route.
- The API's CORS allows only `http://localhost:5173`, so any UI that talks to a real API must run on exactly that origin. To compare the baseline UI, stop the head Vite and start the baseline on 5173 pointed at `:8011`.
- Do not run tool calls in parallel when they `cd`: they share one shell and the cwd resets, so frontend commands silently ran at the repo root.
- In edit mode a task title is an input value, not text, so text locators stop matching.
- The type-ahead hides tags already on the item; do not assert it suggests them.
- The default `GET /trade-groups` fills only `total_pnl`; `realized_pnl` needs `include_intraday=true`.
- Postgres in the container stops between turns: `pg_ctlcluster 16 main start`.
- `uv run` needs `--extra mcp` for the MCP/semantic checks and `--group dev` in a baseline worktree.

## Part A - black-box API (curl against :8010)

`A=localhost:8010/api/v1`, `-H 'content-type: application/json'`. Verified-good values from a dry run are given as **expected**; anything else is a finding.

| # | Do | Expected |
|---|---|---|
| A1 | `POST /tag-links` tags `["Long Beta"]` on the first seeded live fill (`make_exec_id(101)`) | `changed: 2`; both live fills (`…101`, `…102`) show the tag in `GET /trade-executions` |
| A2 | `POST /tags {"value":"long_beta"}` | Returns the **same** tag id and display `Long Beta` (names fold case/space/`-`/`_`) |
| A3 | `POST /tags` with `"created_by":"bob"` | 400 |
| A4 | `POST /tasks` with `"tags":[9999]` | 404 (not a 500 FK error) |
| A5 | `POST /trade-groups {"name":"z","strategy_tag_id":1}` | 422 (renamed field is rejected, not ignored) |
| A6 | `GET /trade-groups?strategy_tag=wheel` and `?theme_tag=oil` | 400 each; `GET /themes` 404; `GET /reports/pnl/trade-groups?group_by=theme` 400 |
| A7 | `GET /trade-groups` | `CL roll` Wheel `total_pnl 110.0`; `NG spread` `2075.0` (75 realized + 2000 unrealized); `ES hedge` `None` |
| A8 | `GET /positions` | Three rows (CL, NG `source: settled`; ES `source: live`), each with `tags` and `open_task_count` |
| A9 | Attach/detach tags on each entity type: `trade`, `position`, `trade_group`, `task`, `live_execution` | 201/200; `GET` of the corresponding list endpoint shows the chip; detach removes it; double-attach is idempotent (`changed: 0`) |
| A10 | `PATCH /tags/{id}` rename onto an existing name | 409. Rename to a free name works. Recolor, then `{"color": null}` clears it |
| A11 | Merge tag X into Y (`POST /tags/{id}/merge`), then archive/unarchive Y | Links move to Y with dedupe; X is gone; ended links keep their dates; archived tags drop out of `GET /tags` unless `include_archived=true`. **Record what happens to chips already on items** |
| A12 | `GET /tags/search?all=a&any=b,c&none=d&entity_type=…` and repeated-param form | Same all/any/none semantics both ways; labels and tags only, no P&L |
| A13 | Tasks: create with links + tags; `PATCH` status through `todo → in_progress → done → todo`; edit title/notes; `DELETE` | `completed_at` set on done and **cleared** on reopen; empty title 400; bad status 400 |
| A14 | Task filters: `status`, `include_done`, `tag`, `strategy_id`, `trade_group_id`, `symbol` | Done hidden by default; `symbol` matches tasks linked to a trade/live fill/position on that symbol |
| A15 | Link a task to a group, then `DELETE /trade-groups/{id}` | The **task survives**; only its link disappears |
| A16 | Strategies: create twice with different casing; rename collision; delete a strategy that a group uses | Idempotent create; 409; 409 |
| A17 | `PATCH /trade-groups/{id}` with `{"strategy_id": null}` vs omitting the field | `null` clears the strategy; omitted leaves it unchanged; unknown id 404 |
| A18 | `GET /tags?q=%25` and `q=a_b` (LIKE metacharacters), a 1,000-character tag, unicode/emoji tags | No 500s; `%`/`_` are matched literally |

**Concurrency probes (unit tests cannot help here: they run in one rolled-back transaction).** Fire 20 parallel identical requests and look for 500s or duplicate rows.

```bash
seq 20 | xargs -P20 -I{} curl -s -o /dev/null -w "%{http_code}\n" -X POST $A/tag-links \
  -H 'content-type: application/json' \
  -d '{"tags":["race-tag"],"items":[{"entity_type":"trade_group","id":1}]}' | sort | uniq -c
```

Do the same with `POST /tags {"value":"race-new"}` (new name, 20-way) and with `POST /tasks/{id}/links`. The code does select-then-insert guarded by partial unique indexes; the expected-correct outcome is all 2xx and exactly one row. A 500 here is a real finding. Check row counts with a read-only `SELECT` on `ngv_verify`.

## Part B - sync paths and non-broker paths, end to end

The unit tests exercise these inside one rolled-back transaction. You are checking the same invariants with **real commits**, then reading the result through the **HTTP API**. Mirror the matching test in `tests/test_tags_and_tasks.py` / `tests/test_position_sync_flat.py` in a short script against `ngv_verify` (use `tests/trade_group_factories.py` helpers, call `session.commit()`), then query the API.

| # | Scenario (test to mirror) | Expected via API |
|---|---|---|
| B1 | Tag + task-link a live fill, then settle it: insert a settled `TradeExecution` with the **same** `ib_exec_id`, run `carry_over_settled_group_links(session)`, commit (`test_live_tags_and_tasks_move_to_the_settled_trade`) | `/trade-executions` shows the tag on the **settled** row/trade; the live link rows are gone; a second run adds nothing |
| B2 | Combo summary settles onto several legs (`test_combo_summary_tags_fan_out_onto_settled_legs`) | Every settled leg's trade carries the tag; no duplicates |
| B3 | Add a third live fill (same `permId`) after tagging, run `inherit_order_links` (`test_late_partial_fill_inherits_its_orders_tags`) | New fill carries the order's tags |
| B4 | Tag a position, delete its `positions` and `live_positions` rows, run `end_flat_position_tags` | `ended_at` set; chip hidden in `/positions`; `/tags/search` hides it unless `include_ended=true`; re-tagging opens a **new** link |
| B5 | Same as B4 but the settled snapshot (`positions.as_of_date`) is **older** than the tag's assigned date | Tag does **not** end (absence proves nothing: Flex drops positions opened today) |
| B6 | Fully flat account: run `sync_flex_positions` with an empty-`OpenPositions` statement vs one with the section missing (`tests/test_position_sync_flat.py`) | Empty section: account's rows cleared, tags ended, dated by statement `toDate`. Missing section/statement: nothing changes |
| B7 | Order and contract paths without a broker (#344, #348): call `find_contracts_with_fallback` with no TWS; then map every place an order status is written (`transition_order_status`, bare `order.status =`) | The enqueued `contracts.sync` payload matches what `handle_contracts_sync` in `src/workers/jobs.py` reads (same keys, same types). Every status write either goes through `transition_order_status` or is justified, and each transition used is allowed by the transition table; flag any bare write that bypasses it |

## Part C - baseline vs head diff (catches silent behavior drift)

**C1. Read endpoints.** With both APIs up on the **same** seeded database, snapshot read endpoints and diff.

```bash
for p in trade-groups "trade-groups/1" "trade-groups/2" "trade-groups/3" trade-executions positions \
         trades strategies "reports/pnl/trade-groups?group_by=strategy"; do
  curl -s "localhost:8011/api/v1/$p" | python3 -m json.tool --sort-keys > /tmp/base.json
  curl -s "localhost:8010/api/v1/$p" | python3 -m json.tool --sort-keys > /tmp/head.json
  echo "== $p"; diff /tmp/base.json /tmp/head.json | head -20
done
```

Expected differences: the baseline has the tag fields too (tags landed before it), so look hard at **everything else**. Review any difference in P&L figures (`total_pnl`, `realized_pnl`, `intraday_*`, `by_account`), counts, or ordering. Repeat with `?include_intraday=true` and `?account_id=1` on the list/detail endpoints, after adding a live position with a quote (`make_live_position`, `make_quote`). Known and intended: trades realized P&L now sums combo summaries **plus** standalone rows (was: combo summaries only). Confirm it matches `tests/test_execution_pnl.py` and does not double count any seeded data. Also intended: a trade-group detail with no `(account, con_id)` pairs now reports `intraday_realized_pnl` instead of `null`.

**C2. Ingest differential (#338).** Feed the same synthetic FlexQuery rows and TWS fills to baseline `67e99f8` and to head, each into its **own fresh migrated database**, and diff `trades` and `trade_executions` column by column (normalize ids and timestamps). The repo's own fixtures in `tests/test_trade_sync_flexquery.py` and `tests/test_trade_sync_tws.py` are the input. Run them in several batches:

- initial load;
- an extra partial fill plus a third revision of an existing execution;
- an idempotent rerun of the same input;
- for TWS, a BAG (combo) fill arriving after its legs.

Expected: rows identical. Only `inserted_executions_count` / `updated_executions_count` differ (baseline reported 0 inserted for Flex and over-counted TWS). Any other column difference is a finding.

**C3. Service differential.** Call `compute_trade_group_pnl` and `trade_group_total_pnls` directly in both trees against one database and diff the results for every seeded group (and again after the C1 live-position and quote additions). Expected: identical figures.

## Part D - MCP and semantic layer

- **D1. MCP tools.** `uv run --extra mcp python -c "from src.mcp import semantic_server as s; ..."` with `NGV_API_URL=http://localhost:8010/api/v1` and `NGV_AGENT_NAME=verify-bot`. Call `create_tag`, `tag_items`, `find_by_tags`, `create_task`, `update_task`, `link_task`. **Expected:** writes succeed; items show `created_by: "agent:verify-bot"`; the UI shows the `AI` badge on them; there are **no** tools to rename/merge/archive tags.
- **D2. Semantic layer.** Set `NGV_SEMANTIC_DATABASE_URL` to the `ngv_verify` URL (a superuser is fine here; production uses a read-only role) and call `describe_semantic_model`, `find_trade_groups("roll")`, `trade_group_pnl("CL roll")`, and `query_metric` with a `trade_group` filter. **Expected:** the dimension is `trade_group` (not `tag`), synonyms include "campaign", and `CL roll` reports about 110. A filter on the old name `tag` should error and list the valid dimensions.
- **D3. Tool-spec comparison (#347).** Compare the tradebot's published tool specs on baseline against `tests/snapshots/tradebot_tool_specs.json`. Expected: 14 of 18 identical; the other 4 differ only by #348 description text and the #318 `tag` → `trade_group` rename. Any other difference is a finding.

## Part E - the UI against the real API

Start Vite on exactly `localhost:5173` (CORS), pointed at the API:

```bash
cd frontend && VITE_API_BASE_URL=http://localhost:8010/api/v1 bunx --bun vite --host localhost --port 5173 --strictPort
```

Use Playwright (preinstalled Chromium; **do not** run `playwright install`; resolve the package from `$(npm root -g)/playwright`). Apply the Playwright gotchas above (`load` plus polling, never `networkidle`; kill by PID).

Flows to drive (screenshot each; compare behavior to the spec, not to your taste):

- **E1. Positions.** `+ tag`, type-ahead shows usage counts, Enter creates a new tag, `×` removes; reload and confirm persistence; `+ task` creates a linked task; the task badge links to Tasks. Agent-applied chips (from Part D) carry `AI`.
- **E2. Trades.** Per-order checkboxes, "select all", bulk **Add tag** / **Remove tag** across a settled order and an unsettled live order; message reads "Tagged N items". Group-assign flow still works. This page was split in #332 (unreviewed).
- **E3. Tags page** (split in #355, not yet verified). `/tags?all=long-beta`, `?any=…&none=…&tab=positions`; state lives in the URL and survives reload; rename / recolor / merge / archive; results are tabbed Trades | Positions | Trade groups | Tasks and each row links somewhere sensible (including a trade with no symbol → `/trades`).
- **E4. Tasks page.** Create, one-click status cycle, **Done** button, edit, delete (confirm dialog), filters (status, tag, symbol, strategy, group), "Show done" toggle; a closed position link shows "(closed)". Double-click **Done** quickly: expect one PATCH, not two.
- **E5. Strategies** (#319, #335 unreviewed split). Pick a group, change its strategy in the edit form (including "No strategy"); the page follows the group to its new strategy; archived-strategy edge case; group detail shows a Tasks section with quick-add. The Strategy P&L table (#356) and the trade-group picker (#357) are covered in E8 and E1/E2.
- **E6. Pricing** (#336 unreviewed split; #337 lazy load). Build a structure, save, load, delete (also with the API stopped to confirm "Delete failed: …" appears and the structure stays selected), fetch a leg price. Confirm the page loads lazily without a blank flash or console errors.
- **E7. Job watcher (#331).** In Positions click a sync button; with no worker running the job stays queued. Then mark that job `completed` in `ngv_verify` (throwaway DB, fixture write): **with** `POST /api/v1/events/notify-job` (`{"job_id":N,"event":"job.updated"}`) the page refreshes immediately; **without** it the page must still refresh within about 10 seconds while the SSE stream is connected. Repeat with the API's SSE blocked.
- **E8. Sort and privacy (#342, #349, #356).** Turn privacy mode on and click every sortable header on Positions and Strategy P&L, baseline vs head, in demo mode. Expected: same row order for the same header and direction; money and quantity cells stay masked after every sort and after reload.
- **E9. Pricing cascade (#340).** Seed a fake CL futures curve and FOP option chain in `ngv_verify`. Compare the leg cascade on baseline UI+API vs head UI+API: expiry → dependent selects → type switch → add leg → instrument switch. Expected: the same options offered at each step and the same resulting leg fields.

**Baseline comparison for the UI.** The API's CORS allows only `http://localhost:5173`, so a baseline UI that talks to a real API must own that port: stop the head Vite, start the baseline (`/tmp/ngv-base/frontend`) on 5173 pointed at `:8011`. For demo-mode comparison (`?demo=1`, no API needed) the baseline and head can run side by side on other ports. Load every route in `src/App.tsx` on both and diff the visible `main` text and screenshots. The only expected differences are the Tags/Tasks surfaces, the new strategy picker, and anything listed in "What changed since".

## Part F - demo mode, docs, and housekeeping

- **F1.** Every route with `?demo=1` renders with no page errors (the lone `ERR_CONNECTION_REFUSED` for the SSE stream is expected).
- **F2.** `uv run python scripts/docs_check.py` and `docs_index.py` leave the tree clean.
- **F3.** Raw links to `media` branch images in `README.md` and `docs/design/tags-and-tasks.md` return HTTP 200 and show the right picture (`curl -sI <url>`).
- **F4.** `git status` is clean at the end; no stray files, no leftover worktree, no processes.
- **F5.** Static sanity: `uv run ruff check --select F401,F821 src` is clean; `uv run pyright src` reports **80** errors on `main` (all pre-existing). More than 80 is a regression.
- **F6.** Test suites: full pytest 541 tests and the frontend suite 202 tests pass (`bun run typecheck && bun run lint && bun test && bun run build` in `frontend/`). Record any count drift.

## Report format

Write one markdown report. Lead with a verdict (ship / ship-with-fixes / do-not-ship), then a table of every scenario ID above (A1.., B1.., C1.., D1.., E1.., F1..) with **PASS / FAIL / BLOCKED / NOT RUN** and one line of evidence. Then a **Findings** section, most severe first, each with: title; severity (data-loss/wrong-numbers > crash/500 > wrong UX > cosmetic); exact reproduction (commands or click path); expected vs actual with raw output; whether baseline `67e99f8` behaves the same; your confidence. Include a short "Could not verify" list with reasons. Do not pad: a clean pass should be a short report.

## Appendix: `seed_verify.py`

```python
"""Seed a THROWAWAY database with fake, anonymized data for dynamic verification.

Run from the repo root with DB_* pointing at the throwaway DB (never dev/prod):
    DB_NAME=ngv_verify ENV=verify uv run python seed_verify.py
Refuses to run twice. Delete the file afterwards.
"""

import sys
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Account, Strategy
from tests.trade_group_factories import (
    ACCOUNT_MAIN,
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
    make_live_position,
    make_position,
    now,
)

with Session(get_engine()) as s:
    if s.execute(select(Account.id).where(Account.account == ACCOUNT_MAIN)).first():
        sys.exit("already seeded; drop and recreate the throwaway DB to reseed")

    acct = make_account(s)
    wheel = Strategy(name="Wheel", normalized_name="wheel", created_by="user")
    cal = Strategy(name="Calendar", normalized_name="calendar", created_by="user")
    s.add_all([wheel, cal])
    s.flush()

    g_cl = make_group(s, "CL roll", account_id=acct.id)
    g_cl.strategy_id = wheel.id
    g_ng = make_group(s, "NG spread", account_id=acct.id)
    g_es = make_group(s, "ES hedge", account_id=acct.id)

    # Settled fills (each is its own trade), grouped.
    make_execution(s, group=g_cl, account=acct, con_id=CON_CL, exec_id=make_exec_id(1), realized=150.0)
    make_execution(s, group=g_cl, account=acct, con_id=CON_CL, exec_id=make_exec_id(2), realized=-40.0, side="SELL", quantity=-1.0)
    make_execution(s, group=g_ng, account=acct, con_id=CON_NG, exec_id=make_exec_id(3), realized=75.0, raw_symbol="NG")
    make_execution(s, group=g_es, account=acct, con_id=CON_ES, exec_id=make_exec_id(4), realized=None, raw_symbol="ES")

    # Settled positions (snapshot dated 3 days ago so freshly-assigned tags stay open).
    for con in (CON_CL, CON_NG):
        make_position(s, account=acct, con_id=con, as_of_date=(now() - timedelta(days=3)).date())
    # A live-only position and a two-fill live order (same permId) for fan-out checks.
    make_live_position(s, account=acct, con_id=CON_ES)
    f1 = make_live_execution(s, account=acct, con_id=CON_ES, exec_id=make_exec_id(101), group=g_es)
    f2 = make_live_execution(s, account=acct, con_id=CON_ES, exec_id=make_exec_id(102))
    f1.ib_perm_id = f2.ib_perm_id = 424242
    s.commit()
    print("seeded: account", acct.id, "| strategies", wheel.id, cal.id, "| groups", g_cl.id, g_ng.id, g_es.id)
```
