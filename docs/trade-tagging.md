# Trade Tagging

Current-state documentation for strategy tags, trade groups, execution assignment, and the tagging UI.

## Purpose

The trade-tagging system lets the desk organize executions into lifecycle groups and label those groups with strategy metadata.

Today the live system supports:

1. strategy catalog CRUD
2. theme catalog CRUD at the API layer
3. trade-group CRUD
4. execution-to-trade-group assignment, unassignment, and reassignment
5. assignment history and a timeline view
6. trades-page assignment into groups

## Core Data Model

### `trade_groups`

Lifecycle container for a campaign or position cluster.

Main fields:

1. `id`
2. `account_id`
3. `name`
4. `notes`
5. `status` with values `open`, `closed`, `archived`
6. `opened_at`
7. `closed_at`
8. `opened_by`
9. `closed_by`
10. `created_at`
11. `updated_at`

Notes:

1. `account_id` is nullable at creation
2. when the first execution is assigned, the group auto-populates `account_id` from that execution
3. assignment is intentionally cross-account in V1, so group membership is not limited by `account_id`

### `trade_group_executions`

Current execution-to-group membership table.

Properties:

1. one execution can belong to only one trade group at a time
2. stores `source`, `created_by`, `confidence`, and `assigned_at`
3. is the source of truth for current membership

### `trade_group_execution_events`

Assignment history table.

Tracks:

1. `assigned`
2. `reassigned`
3. `unassigned`

Each row stores provenance and optional reason text.

### `tags`

Shared tag catalog table for:

1. `strategy`
2. `theme`
3. `risk_intent`
4. `hedge_type`
5. `holding_horizon`

`value` is normalized into `normalized_value`, and `(tag_type, normalized_value)` is unique.

### `tag_links`

Generic tag attachment table across entities.

Supported `entity_type` values:

1. `orders`
2. `trades`
3. `trade_executions`
4. `trade_groups`

Important current rule:

1. a trade group can have only one primary strategy tag

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
8. `POST /api/v1/trade-executions/{execution_id}/trade-group:reassign`
9. `GET /api/v1/trade-groups/{trade_group_id}/timeline`

#### `GET /trade-groups`

Supported filters:

1. `account_id`
2. `status`
3. `strategy_tag`
4. `theme_tag`
5. `q`
6. `opened_from`
7. `opened_to`
8. `limit`

The response includes a derived `primary_strategy_value`.

#### `POST /trade-groups`

Creates a group with:

1. required `name`
2. optional `notes`
3. optional `strategy_tag_id`
4. provenance fields such as `source`, `created_by`, and `confidence`

Behavior:

1. groups are created with `status="open"`
2. a primary strategy tag link is created immediately when `strategy_tag_id` is supplied

#### `PATCH /trade-groups/{id}`

Supports edits to:

1. `name`
2. `notes`
3. `status`
4. `closed_at`
5. `closed_by`

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

## Tag and Catalog API

Routes in `src/api/routers/tags.py`.

Implemented endpoints:

1. `GET /api/v1/tags`
2. `POST /api/v1/tags`
3. `POST /api/v1/tag-links`
4. `DELETE /api/v1/tag-links/{tag_link_id}`
5. `GET /api/v1/strategies`
6. `POST /api/v1/strategies`
7. `PATCH /api/v1/strategies/{strategy_id}`
8. `DELETE /api/v1/strategies/{strategy_id}`
9. `GET /api/v1/themes`
10. `POST /api/v1/themes`
11. `PATCH /api/v1/themes/{theme_id}`
12. `DELETE /api/v1/themes/{theme_id}`

Current behavior:

1. strategies and themes are catalog tags backed by `tags`
2. duplicate normalized values are prevented
3. deleting a strategy or theme fails if it is still linked
4. generic tag-link creation works for multiple entity types, not only trade groups

## Live UI

### Trades page assignment

The trades table supports group assignment and unassignment from the row UI.

Current behavior:

1. users can search open trade groups from the trades page
2. assignment writes execution-level membership, not just trade-level labeling
3. unassignment removes those execution memberships

This makes the trades page the main operational entry point for tagging fills into groups.

### Tagging workspace

The main tagging UI is `frontend/src/components/TradeTaggingPage.tsx`.

It currently supports:

1. viewing the strategy catalog
2. creating strategies
3. viewing trade groups filtered by selected strategy
4. creating trade groups under the selected strategy
5. viewing group detail
6. editing group name, notes, and status
7. deleting trade groups
8. viewing a read-only timeline

The current page does not provide:

1. direct execution assignment from inside the tagging page
2. theme management UI
3. generic tag-link editing UI
4. UI for trade-group linking such as manual roll-link creation

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
3. operator manages strategy and trade-group metadata in `/tagging`
4. timeline and counts update from the group detail endpoints

## Important Constraints

1. execution attribution is the live membership model; trade groups do not directly own trades or orders
2. a trade group can have one primary strategy tag, not multiple primary strategies
3. cross-account assignment is allowed in the current implementation
4. delete-group behavior unassigns executions and records unassignment events before deleting the group
5. some modeled capabilities, such as `trade_group_links`, exist in storage but are not yet fully surfaced in UI flows

## Related Files

1. `src/models.py`
2. `src/api/routers/trade_groups.py`
3. `src/api/routers/tags.py`
4. `frontend/src/components/TradesTable.tsx`
5. `frontend/src/components/TradeTaggingPage.tsx`
