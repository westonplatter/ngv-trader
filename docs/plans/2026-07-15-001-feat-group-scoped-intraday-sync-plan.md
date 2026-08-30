---
title: "feat: Scope intraday TWS sync to a single trade group"
type: feat
status: active
created: 2026-07-15
---

# feat: Scope intraday TWS sync to a single trade group

## Summary

Add an optional `trade_group_id` to the intraday TWS overlay sync so a per-group
"Refresh Live (TWS)" only re-fetches **marks** for the contracts that group
holds, instead of the whole account. The expensive part of the job — the
`reqTickers` fan-out over every held contract (`_fetch_tickers`) — is the only
thing that gets scoped. Positions and fills stay account-wide (they are cheap to
fetch and upsert-keyed, so scoping them buys nothing and risks stranding other
groups' live rows). When no `trade_group_id` is supplied the job behaves exactly
as today.

---

## Problem Frame

### Today the sync is fully account-wide

`run_intraday_sync(engine, ib)` (`src/services/intraday_sync_tws.py:354`)
fetches `ib.positions()` and `ib.fills()` — both return the entire TWS session's
data — runs `_fetch_tickers` over **all** held contracts, then writes
`live_positions`, `LatestQuote`, and `live_executions` globally. There is no
group/account/contract filter anywhere. The API endpoint
(`POST /positions/sync/intraday-tws`, `enqueue_intraday_sync` at
`src/api/routers/positions.py:417`) accepts an `account_code` today but never
uses it; the worker (`handle_intraday_sync_tws`, `src/workers/jobs.py:638`)
calls `run_intraday_sync` with no scoping argument.

### Why scoping is necessarily a post-fetch filter

`ib.positions()` and `ib.fills()` are inherently account-wide from IB — TWS has
no "only this group" request. So group-scoping can only be a **post-fetch
filter** on what we do with the results. The relevant lever is _which contracts
we request marks for_: `_fetch_tickers` is the slow, rate-limited call; fills and
positions are a single cheap round-trip each.

A trade group resolves to a set of `con_id`s via its members:
`TradeGroupExecution` → `TradeExecution.con_id` (`src/models.py:384`), plus
provisional `TradeGroupLiveExecution.con_id` links (`src/models.py:544`). We can
compute that set and intersect it with the held contracts before requesting
tickers.

---

## Key Design Decision

**Scope only the marks fetch; keep positions, fills, and purge account-wide.**

| Approach                                                                | Scopes what           | Delivers the speed win         | Stranding risk                                                                                                                       | Verdict                                    |
| ----------------------------------------------------------------------- | --------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| **A. Scope only `_fetch_tickers`** to `held ∩ group_con_ids`            | Marks (`LatestQuote`) | Yes — `reqTickers` is the cost | None — positions/fills still upsert globally                                                                                         | **Recommended**                            |
| B. Also narrow `live_positions` / `live_executions` writes to the group | Marks + row writes    | Yes                            | Yes — other groups' live rows go unrefreshed for no benefit, and narrowing which fills get written can drop rows another group needs | Rejected — more code, more risk, no upside |
| C. No scoping (status quo)                                              | —                     | No                             | —                                                                                                                                    | Doesn't meet the ask                       |

**Rationale.** The entire value of a per-group refresh is a _fast_ mark update
for that group's instruments. `reqTickers` is the only slow, fan-out call, so
scoping it is where the value is. Positions and fills are one cheap fetch each
and are written as `con_id` / `ib_exec_id` upserts, so writing them all every run
is harmless and keeps other groups' live rows correct. Narrowing writes (Option
B) adds branching and a real stranding hazard to save nothing.

**One reorder required.** Group `con_id`s must be resolved from the DB _before_
`_fetch_tickers` runs. Today the session opens only after tickers are fetched
(`src/services/intraday_sync_tws.py:372-375`). The plan resolves the group's
con_id set in a short read at the top of the function, then filters
`held_contracts` before the ticker call.

**Empty/closed group.** If the group resolves to no currently-held con_ids,
`_fetch_tickers` is skipped entirely (no marks refreshed) while positions/fills
still sync globally. That is a valid, fast near-no-op — not an error.

---

## Implementation Units

### U1. Resolve a group's con_id set and scope the marks fetch

**Goal:** `run_intraday_sync` accepts an optional `group_id` and, when set,
requests marks only for the group's held contracts.
**Files:** `src/services/intraday_sync_tws.py`,
`tests/services/test_intraday_sync_tws.py` (or the existing test module for this
service).
**Approach:**

- Change the signature to `run_intraday_sync(engine, ib, group_id: int | None = None)`.
- Add a helper `_group_con_ids(session, group_id) -> set[int]` that unions
  `TradeExecution.con_id` for the group's `TradeGroupExecution` members with
  `TradeGroupLiveExecution.con_id` for the group, dropping `None`.
- Near the top of `run_intraday_sync`, when `group_id` is not None, open a short
  session to resolve the con_id set, then filter `held_contracts` to that set
  **before** `_ensure_market_data_exchange` / `_fetch_tickers`. When `group_id`
  is None, behavior is unchanged.
- Leave `_write_live_positions`, `_write_fills`, and `_purge_settled` untouched
  (still account-wide).
- Include `group_id` (and the resolved con_id count) in the returned `counts` /
  log line for observability.
  **Patterns to follow:** existing session usage in `run_intraday_sync`; the
  `select(...).scalars()` style already used in `_purge_settled`
  (`src/services/intraday_sync_tws.py:347`).
  **Test scenarios:**
- Happy path: `group_id` set → `_fetch_tickers` receives only contracts whose
  con_id is in the group set; `quotes` count reflects only those.
- Unscoped: `group_id=None` → tickers requested for all held contracts (current
  behavior, regression guard).
- Group holds a con_id not currently in `ib.positions()` → that con_id is
  silently dropped (intersection with held), no error.
- Empty result: group resolves to zero held con_ids → `_fetch_tickers` skipped,
  positions/fills still written globally.
- Scoping does not narrow writes: with `group_id` set, `live_positions` and
  `live_executions` still receive all account rows (assert other-group con_ids
  are still upserted).

### U2. Thread `trade_group_id` through the API and worker

**Goal:** The enqueue endpoint accepts `trade_group_id` and the worker passes it
to `run_intraday_sync`.
**Dependencies:** U1.
**Files:** `src/api/routers/positions.py`, `src/workers/jobs.py`,
`tests/api/test_positions_router.py` (or existing router test module).
**Approach:**

- Add `trade_group_id: int | None = None` to `IntradaySyncRequest`
  (`src/api/routers/positions.py:120`).
- In `enqueue_intraday_sync` (`:417`), put it in the job payload when present,
  mirroring the existing `account_code` handling.
- In `handle_intraday_sync_tws` (`src/workers/jobs.py:638`), read
  `payload.get("trade_group_id")`, coerce to `int | None`, and pass it as
  `run_intraday_sync(engine=engine, ib=ib, group_id=...)`.
  **Patterns to follow:** the `account_code` payload pattern already in
  `enqueue_intraday_sync` and `enqueue_option_metrics_sync`.
  **Test scenarios:**
- POST with `trade_group_id` → job payload contains `trade_group_id`.
- POST without it → payload omits the key (unchanged enqueue behavior).
- Worker: payload with `trade_group_id` → `run_intraday_sync` called with
  matching `group_id` (assert via mock).
- Worker: payload without it → `run_intraday_sync` called with `group_id=None`.

### U3. Pass the selected group id from the per-group refresh button

**Goal:** The "Refresh Live (TWS)" button on the trade-group view scopes to the
open group.
**Dependencies:** U2.
**Files:** `frontend/src/components/TradeTaggingPage.tsx`.
**Approach:** In `kickOffIntradaySync` (`~:515`) include
`trade_group_id: selectedGroupId` in the request body when `selectedGroupId` is
non-null. The account-wide button in `frontend/src/components/TradesTable.tsx`
stays as-is (sends no `trade_group_id` → account-wide), since it has no single
group context.
**Test scenarios:** `Test expectation: none -- one-line payload addition, covered
end-to-end by U1/U2 tests and manual verification below.`

---

## Verification

- **Unit:** U1's scoping tests prove `_fetch_tickers` is restricted to the group's
  held con_ids and that writes stay global. U2's tests prove the id threads
  through API → payload → handler.
- **Manual (ENV=prod, per repo convention):** open a group with a few held
  contracts, click "Refresh Live (TWS)", and confirm (a) the job completes
  faster than the account-wide run, (b) `LatestQuote` timestamps advance only for
  that group's con_ids, and (c) `live_positions` / `live_executions` for other
  groups are unchanged (not stranded, not deleted).
- **Regression:** trigger the account-wide button (no `trade_group_id`) and
  confirm marks refresh for all held contracts as today.

---

## Scope Boundaries

- **Not** changing how positions or fills are fetched or written — they remain
  account-wide upserts.
- **Not** scoping `LatestQuote` deletion or `_purge_settled` — global.
- **Not** adding a `group_id` column to any table; the group→con_id resolution is
  a read-time query.
- **Not** touching the account-wide `TradesTable` button behavior.

### Deferred to Follow-Up Work

- Scoping option-metrics sync (`run_option_metrics_sync`) to a group by the same
  pattern, if per-group greeks refresh is later wanted.
