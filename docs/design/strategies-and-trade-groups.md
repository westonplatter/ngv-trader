---
topics: ["trade-groups", "strategies", "executions", "frontend"]
code_dirs_or_files:
  [
    "src/api/routers/trade_groups.py",
    "src/api/routers/strategies.py",
    "src/services/trade_group_instruments.py",
    "frontend/src/components/StrategiesPage.tsx",
    "frontend/src/components/StrategyPnlTable.tsx",
  ]
description: Strategies and trade groups — data model, execution assignment and history, trade-group and strategy APIs, position chips, the Strategy P&L table, and the Strategies workspace.
---

# Strategies and Trade Groups

Current-state documentation for strategies, trade groups, execution assignment, and the Strategies UI.

The UI surface for all of this is the **Strategies** page at `/strategies`
(`frontend/src/components/StrategiesPage.tsx`), with a book-wide **Strategy P&L**
table at `/strategies/table`. Strategies live in their own `strategies` table and
a group points at one through `trade_groups.strategy_id`. Strategies and trade
groups never use the word "tag": that is reserved for the free-form tags in
[tags-and-tasks.md](tags-and-tasks.md).

## Purpose

The strategies and trade-groups system lets the desk organize executions into lifecycle groups and label those groups with strategy metadata.

Today the live system supports:

1. strategy catalog CRUD
2. trade-group CRUD
3. execution-to-trade-group assignment, unassignment, and reassignment
4. assignment history and a timeline view
5. trades-page assignment into groups

> The TradeGroup executions view also supports an optional **intraday TWS
> overlay**: a "Refresh Live (TWS)" button surfaces live current-state P&L
> (live qty/mark/unrealized + intraday totals) alongside the settled snapshot,
> with a freshness indicator. The overlay is additive and degrades to settled
> values when no live data is present. See
> [core/intraday-tws-overlay.md](intraday-tws-overlay.md).

## Core Data Model

### `trade_groups`

Lifecycle container for a campaign or position cluster.

Main fields:

1. `id`
2. `account_id`
3. `name`
4. `notes`
5. `meta_yaml`
6. `strategy_id` (nullable FK to `strategies`)
7. `status` with values `open`, `closed`, `archived`
8. `opened_at`
9. `closed_at`
10. `opened_by`
11. `closed_by`
12. `created_at`
13. `updated_at`

Notes:

1. `account_id` is nullable at creation
2. when the first execution is assigned, the group auto-populates `account_id` from that execution
3. assignment is intentionally cross-account in V1, so group membership is not limited by `account_id`
4. `meta_yaml` holds an optional free-form YAML "management spec" (target delta, estimated entry/exit dates, dated profit targets, plus arbitrary keys). Stored verbatim; validated on write; `GET /trade-groups/{id}` returns the parsed form as `meta`. See [core/trade-group-meta-yaml.md](trade-group-meta-yaml.md).

### `trade_group_executions`

Current execution-to-group membership table.

Properties:

1. one execution can belong to only one trade group at a time
2. stores `source`, `created_by`, `confidence`, and `assigned_at`
3. is the source of truth for current membership

### `trade_group_live_executions`

Provisional membership for **unsettled TWS fills**, keyed by `ib_exec_id` (the
stable id shared with the eventual settled `trade_executions` row). Lets the desk
preemptively assign a live fill to a group before it settles. On settlement the
carry-over (`src/services/group_link_carryover.py`) folds the link into
`trade_group_executions` and drops the live row; it runs in both the intraday
purge and the FlexQuery trade sync. See
[core/intraday-tws-overlay.md](intraday-tws-overlay.md).

### `trade_group_execution_events`

Assignment history table.

Tracks:

1. `assigned`
2. `reassigned`
3. `unassigned`

Each row stores provenance and optional reason text.

### `strategies`

The strategy catalog: `id`, `name`, `normalized_name`, `created_by`,
`created_at`, `archived_at`. `name` is normalized (trimmed, lowercased, runs of
whitespace collapsed) into `normalized_name`, which is unique.

A trade group has at most one strategy, held in `trade_groups.strategy_id`
(`ON DELETE RESTRICT`). Strategies were once `tags` rows with
`tag_type = 'strategy'` linked through `tag_links`; migration `e68def4337bb`
moved them out, keeping their ids.

### `trade_group_links`

Stores links between trade groups, for example roll relationships.

Current state:

1. the model and timeline read path exist
2. delete logic cleans up related links
3. there is no dedicated UI or public creation endpoint in the current implementation

## Live API Surface

### Trade groups

Routes in `src/api/routers/trade_groups.py`.

Implemented endpoints:

1. `GET /api/v1/trade-groups`
2. `POST /api/v1/trade-groups`
3. `GET /api/v1/trade-groups/{trade_group_id}`
4. `PATCH /api/v1/trade-groups/{trade_group_id}`
5. `DELETE /api/v1/trade-groups/{trade_group_id}`
6. `POST /api/v1/trade-groups/{trade_group_id}/executions:assign`
7. `POST /api/v1/trade-groups/{trade_group_id}/executions:unassign`
8. `POST /api/v1/trade-groups/{trade_group_id}/positions:assign`
9. `POST /api/v1/trade-groups/{trade_group_id}/positions:unassign`
10. `POST /api/v1/trade-groups/{trade_group_id}/live-executions:assign`
11. `POST /api/v1/trade-groups/{trade_group_id}/live-executions:unassign`
12. `POST /api/v1/trade-executions/{execution_id}/trade-group:reassign`
13. `GET /api/v1/trade-groups/{trade_group_id}/timeline`
14. `GET /api/v1/trade-groups/{trade_group_id}/executions`

#### `GET /trade-groups`

Supported filters:

1. `account_id`
2. `status`
3. `strategy` — the strategy name, matched after normalization
4. `q` — free text over the group name and its strategy name
5. `instrument` — case-insensitive regex (`CL.*`, `CL|NG`) over the group's
   derived instruments, falling back to its name
6. `opened_from`
7. `opened_to`
8. `limit`

Plus one opt-in flag, `include_intraday` (default `false`).

The response always includes `strategy_id`, the strategy's name as
`primary_strategy_value`, and the settled
`total_pnl`. With `include_intraday=true` it also carries the split behind that
total — `realized_pnl`, `unrealized_pnl`, `intraday_unrealized_pnl`,
`intraday_realized_pnl`, `intraday_total_pnl`, `marks_as_of`, `live_is_stale` —
and the group's `instruments`. The flag defaults off so the Strategies left
panel and the group picker, which read `total_pnl` alone, pay no overlay cost.

Two behaviors are worth knowing:

- **Every filter is applied before `limit`.** The instrument pattern is a
  correlated SQL `EXISTS`, not a post-fetch filter, so a narrow pattern returns
  matching rows rather than an empty page. A malformed pattern is a `400`.
- **`account_id` scopes the figures, not just the row list.** Group membership
  is cross-account, so a group can hold legs in several accounts. A group is
  listed when it is _owned by_ the account (`trade_groups.account_id`, set from
  its first assigned fill) **or** holds a fill there, and its figures report that
  account's slice — the same numbers `GET /trade-groups/{id}/executions` shows in
  its per-account breakdown. Selecting on ownership alone would hide a
  cross-account group from the account whose capital it is using; keeping the
  ownership arm is what lets a group with no fills yet still appear somewhere.

#### `POST /trade-groups`

Creates a group with:

1. required `name`
2. optional `notes`
3. optional `meta_yaml`
4. optional `strategy_id` (`404` if unknown)
5. `created_by`

Groups are created with `status="open"`.

#### `PATCH /trade-groups/{id}`

Supports edits to:

1. `name`
2. `notes`
3. `meta_yaml` (blank string clears it)
4. `status`
5. `closed_at`
6. `closed_by`
7. `strategy_id` — sets the strategy; an explicit `null` clears it, and
   omitting the field leaves it unchanged

#### Assignment endpoints

Assignment behavior:

1. assignment source must be one of `manual`, `rule`, or `agent`
2. a duplicate assignment to the same group is ignored
3. assigning an already-assigned execution returns `409` unless `force_reassign=true`
4. reassignments update current membership and append an event row
5. unassignments remove current membership and append an event row

#### Timeline endpoint

The timeline is assembled from:

1. current execution assignments
2. assignment-history events
3. trade-group links

Displayed event types are derived from execution side and role, plus assignment history and group-link rows.

## Strategy API

Routes in `src/api/routers/strategies.py`.

1. `GET /api/v1/strategies` (`q`, `limit`, `include_archived`)
2. `POST /api/v1/strategies` (`name`, `created_by`)
3. `PATCH /api/v1/strategies/{strategy_id}` (`name`)
4. `POST /api/v1/strategies/{strategy_id}/archive`
5. `POST /api/v1/strategies/{strategy_id}/unarchive`
6. `DELETE /api/v1/strategies/{strategy_id}`

Behavior:

1. creating a strategy whose normalized name exists returns the existing one
2. renaming onto another strategy's normalized name is a `409`
3. deleting a strategy that any trade group still uses is a `409`

A group's strategy is set through `POST /trade-groups` and
`PATCH /trade-groups/{id}`, not a separate link endpoint.
`GET /reports/pnl/trade-groups?group_by=strategy` rolls groups up by
`trade_groups.strategy_id`.

## Live UI

### Trades page assignment

The trades table supports group assignment and unassignment from the row UI.

Current behavior:

1. users can search open trade groups from the trades page
2. assignment writes execution-level membership, not just trade-level labeling
3. unassignment removes those execution memberships

This makes the trades page the main operational entry point for assigning fills to groups. Its **Group** filter (`?group=all|grouped|ungrouped`) narrows rows by whether they belong to a group, and the **Trade Group** column holds the picker. It also supports assigning/unassigning live (intraday TWS) executions via the `live-executions:assign`/`live-executions:unassign` endpoints.

### Positions page assignment

`frontend/src/components/PositionsTable.tsx` supports group assignment and
unassignment directly from the Positions page, via the
`positions:assign`/`positions:unassign` endpoints (see
[core/intraday-tws-overlay.md](intraday-tws-overlay.md) for how live
positions are computed).

#### Which groups a position row shows

Membership is per-fill, so a position's chips are rolled up from its fills — but
only from the fills that make up the quantity **held right now**. `GET /positions`
walks every settled fill for an `(account_id, con_id)` in execution order and
matches closing quantity against open quantity FIFO; the lots that survive the
walk are the open ones, and only their groups become chips. Ungrouped fills take
part in the matching but contribute no chip. Unsettled TWS fills
(`trade_group_live_executions`) are open by definition and always count.

This matters because the same con_id is routinely re-entered under a new campaign
after an earlier one was closed out. Rolling up all historical fills would stack a
chip for every dead campaign onto the live row.

Fallback: if the FIFO walk leaves no open lots for a position that is actually
held — the fill history does not reconcile, e.g. transferred-in lots or fills
predating the sync window — the row falls back to the unfiltered historical
rollup rather than showing nothing.

Note the read path and the write path differ in scope: `positions:assign` and
`positions:unassign` still fan out to **every** fill on the con_id, including
closed historical lots, not just the open ones.

### Strategy P&L table

`/strategies/table` (`frontend/src/components/StrategyPnlTable.tsx`) is the
book-wide sibling of the Strategies workspace: one row per trade group, with its
strategy, account, instruments, and Realized / Unrealized / Total P&L, filterable
by account, instrument pattern, and status. It is read-only — assignment,
renaming, and status changes stay on the workspace page — and a row click opens
that group in the workspace via `?trade_group_id=`.

Each row's three P&L columns come from the same layer as each other: the
intraday figures when the group has live data, the settled ones otherwise, so
Total always reconciles to Realized + Unrealized. Freshness renders as
`live HH:MM`, an amber `stale HH:MM`, or `settled`. See
[core/intraday-tws-overlay.md](intraday-tws-overlay.md) for how the batched
overlay is computed.

#### Deriving a group's instruments

A trade group has no instrument: it links to executions, and an execution
carries `con_id` but no symbol. `src/services/trade_group_instruments.py`
resolves the **underlying root** as
`COALESCE(contracts.symbol, trade_executions.raw -> 'contract' ->> 'symbol')`.

The security master (`contracts`) is authoritative where present, but it is
incomplete — many traded option `con_id`s never get a row — so the raw payload,
which the FlexQuery sync synthesizes from `underlyingSymbol`, is the fallback.
Both are the underlying root, not the OCC/local symbol (the sync writes that to
`contract.localSymbol`). Where the security master holds a specific contract
symbol rather than a root, the derived list carries that too, which is why a
group can list both `CL` and `CLZ6`.

### Strategies workspace

The main Strategies UI is `frontend/src/components/StrategiesPage.tsx`.

It currently supports:

1. viewing the strategy catalog
2. creating strategies
3. viewing trade groups filtered by selected strategy
4. creating trade groups under the selected strategy
5. viewing group detail
6. editing group name, notes, status, and strategy (moving a group to another
   strategy re-selects that strategy so the group stays in view)
7. deleting trade groups
8. viewing a read-only timeline

The current page does not provide:

1. direct execution assignment from inside the Strategies page
2. UI for trade-group linking such as manual roll-link creation

## Timeline Semantics

The timeline is descriptive, not a full accounting ledger.

Current classification rules:

1. assigned `leg` executions render as adjustment-style events
2. assigned `BUY` / `BOT` executions render as entry-style events
3. assigned sell-side executions render as exit-style events
4. reassignment and unassignment history is included from `trade_group_execution_events`
5. `trade_group_links` render as `roll_linked` events when link rows exist

This gives a compact lifecycle view without changing the underlying execution records.

## Current Workflow

Typical live workflow:

1. executions appear in `/trades`
2. operator assigns a trade's executions to a trade group from the trades page
3. operator manages strategy and trade-group metadata in `/strategies`
4. timeline and counts update from the group detail endpoints

## Important Constraints

1. execution attribution is the live membership model; trade groups do not directly own trades or orders
2. a trade group has at most one strategy
3. cross-account assignment is allowed in the current implementation
4. delete-group behavior unassigns executions and records unassignment events before deleting the group
5. some modeled capabilities, such as `trade_group_links`, exist in storage but are not yet fully surfaced in UI flows

## Related Files

1. `src/models.py`
2. `src/api/routers/trade_groups.py`
3. `src/api/routers/strategies.py`, `src/api/routers/reports.py`
4. `frontend/src/components/TradesTable.tsx`
5. `frontend/src/components/PositionsTable.tsx`
6. `frontend/src/components/StrategiesPage.tsx`, `frontend/src/components/StrategyPnlTable.tsx`, `frontend/src/lib/strategyPnl.ts`
7. `src/services/trade_group_pnl.py` (batched per-group P&L), `src/services/trade_group_instruments.py` (instrument derivation and the pattern filter)
8. `frontend/src/contexts/PrivacyContext.tsx`, `frontend/src/utils/privacy.ts` (privacy-mode masking used throughout the trade-group detail view)
