---
status: NOT IMPLEMENTED
topics:
  [
    "tags",
    "tasks",
    "strategies",
    "trade-groups",
    "positions",
    "agent-tools",
    "frontend",
  ]
code_dirs_or_files:
  [
    "src/models.py",
    "src/api/routers/tags.py",
    "src/api/routers/trade_groups.py",
    "src/services/group_link_carryover.py",
    "src/services/position_sync_flexquery.py",
    "src/mcp/semantic_server.py",
  ]
description: Spec for free-form tags on trades, positions, trade groups, and tasks, plus a simple task list — moving strategies out of the tag tables, data model, sync hooks, API, MCP tools, and UI.
---

# Spec: Tags and Tasks

> **Status: NOT IMPLEMENTED.** Planning is closed; all decisions are settled.
> Delivery 1 (strategies moved out of the tag tables) has shipped; tags and tasks
> have not.

## Goal

- **Tags** are free-form, reusable labels, like sticky notes, that a person
  applies to trades, positions, trade groups, and tasks, such as `long-beta`,
  `risk-off`, and `offset-risk`. They describe an item; they do not group items.
- **Tasks** are simple to-dos (To do → In progress → Done) that link to
  strategies, trade groups, positions, and trades, and can carry tags.
- A local LLM agent can do everything a person can through REST endpoints and MCP
  tools.

## Vocabulary

| Term        | Meaning                                                                                |
| ----------- | -------------------------------------------------------------------------------------- |
| Strategy    | What a trade group is. One primary strategy per group.                                 |
| Trade group | Lifecycle container. Each execution belongs to at most one group.                      |
| Tag         | Free-form label. Many per item, shared across items, never groups them.                |
| Task        | A to-do with a status, linked to any mix of strategies, groups, positions, and trades. |

"Tag" means only the free-form label. Strategies and trade groups never use the
word in UI, API, or code.

Strategies and trade groups are the verified, systematic structure that reporting
is built on. Tags are free-floating decoration and never feed reporting structure.

## Background

The March 2026 tagging core built `tags` / `tag_links` as a generic catalog with
five `tag_type`s (`strategy`, `theme`, `risk_intent`, `hedge_type`,
`holding_horizon`). Only strategies were finished. Themes have API endpoints but
no UI, and the other three types were never surfaced. See
[strategies-and-trade-groups.md](strategies-and-trade-groups.md).

## Decisions

1. **A trade is the order** (`trades`), not the execution. Tagging an order
   covers all its fills.
2. **Live orders can be tagged** before settlement. Order ids do not match
   across sources: TWS keys orders by `permId`, which FlexQuery lacks, and
   FlexQuery groups combos by `brokerageOrderID` with a synthesized summary id.
   See [trades-and-executions-sync.md](trades-and-executions-sync.md) and
   [intraday-tws-overlay.md](intraday-tws-overlay.md). So a live order's tags
   are stored **per fill**, keyed by `ib_exec_id`, the same way trade-group
   assignment of unsettled fills works. Tagging a live order fans out to all of
   its live fills, and a combo is tagged as one unit.
3. **A position is account + contract** (`account_id`, `con_id`), never a
   `positions.id`, because sync replaces rows.
4. **Position tags end when the contract is flat** in both settled
   (`positions`) and live (`live_positions`) data. They are soft-ended
   (`ended_at`), not deleted.
5. **Task links survive a position closing.** The link stays and the UI shows
   the position as closed.
6. **No automatic tagging.** People or agents acting on request apply every tag.
   There are no rules.
7. **Provenance on every write.** `created_by` is `user` or `agent:<name>`.
8. **Trade groups can be tagged.** A tag on a group is a sticky note, separate
   from its strategy.
9. **No reporting on tags in this work.** No P&L, Greeks, or other aggregates
   by tag. That is follow-up work.
10. **Agents create, attach, detach, and search tags, and have full task CRUD.**
    Merging, renaming, and archiving tags is human-only.
11. **Tags are shared across accounts** and can carry an optional color.
12. **Position tags can also be removed by hand** while the position is open.
    Ended position tags are hidden in the UI and readable through the API.
13. **Task defaults.** Fields are title, notes, and status only. Tasks are
    ordered by created date. Done tasks are hidden behind a toggle and never
    auto-deleted. Tasks can link to live orders (per fill), carried over at
    settlement.
14. **Agent access** uses the same trusted local API as the UI, with no separate
    credentials. Agent-applied tags and tasks show a marker in the UI.
15. **Hard break on renamed API routes.** No redirects for the old strategy
    endpoints under `/tags` and `/tag-links`.

## Data model

### Move strategies out of the tag tables

- New `strategies` table (`id`, `name`, `normalized_name`, `created_by`,
  `created_at`, `archived_at`), seeded from `tags` rows where
  `tag_type = 'strategy'`.
- New `trade_groups.strategy_id` FK, backfilled from primary strategy
  `tag_links`. It replaces the `uq_tag_links_primary_strategy_trade_group` index.
- The `theme`, `risk_intent`, `hedge_type`, and `holding_horizon` types are
  dropped, not migrated. They were never used; strategies and trade groups are
  the only live data in these tables.
- All of this is one reversible Alembic migration.

### Tags (repurposed `tags` / `tag_links`)

- `tags`: `id`, `value`, `normalized_value` (unique; case, spaces, `-`, and `_`
  folded), optional `color`, `created_by`, `created_at`, `archived_at`. The
  `tag_type` column goes away.
- `tag_links`: `tag_id`, `entity_type`, `entity_key`, `created_by`,
  `assigned_at`, `ended_at`. The `is_primary`, `tag_type`, and `confidence`
  columns go away.
- `entity_type` values: `trade`, `live_execution`, `position`, `trade_group`,
  `task`.
- `entity_key` identifies the item:
  - `trade`, `trade_group`, and `task`: the row id
  - `position`: `account_id` + `con_id`
  - `live_execution`: `ib_exec_id`, with `account_id` and `con_id`
    denormalized, like `trade_group_live_executions`
  - Typed nullable columns with a per-type check constraint, not a string key.
- Unique on (`tag_id`, entity) among rows where `ended_at` is null.

### Tasks

- `tasks`: `id`, `title`, `notes`, `status` (`todo` | `in_progress` | `done`),
  `created_by`, `created_at`, `updated_at`, `completed_at`.
- `task_links`: `task_id`, `entity_type` (`strategy`, `trade_group`, `position`,
  `trade`, `live_execution`), typed key columns as above, `created_by`, `created_at`.
- Deleting a trade group or strategy drops its links, never the task.
- Deleting a trade group or task drops its tag links.

## Sync hooks

- **Live fill → settled trade.** Resolve each tagged live fill to its settled
  `trade_executions` row, then put the link on that row's parent `trades` row
  and drop the live link. One trade collects the tags of all its fills, deduped
  by the unique index.
  - Resolution reuses the trade-group paths in
    `src/services/group_link_carryover.py`: exact `ib_exec_id` match, plus the
    divergent cases resolved by `src/services/live_reconcile.py` (`leg_strip`,
    `book_event`, and `bag_summary` fanning out onto the settled legs).
  - The carry-over runs wherever the group carry-over runs: the intraday purge,
    the end of the FlexQuery trade sync, and orphan reconciliation.
- **Late partial fills.** A partial fill that arrives after the order was
  tagged inherits the tags of live fills sharing its order key (`ib_perm_id`,
  else `ib_order_id`). This applies within a single TWS order only; it is not
  tag inheritance between orders.
- **Position flat → end tags.** After the FlexQuery position sync and the
  intraday sync, set `ended_at` on `position` tag links whose contract is absent
  from both `positions` and `live_positions`. Never key this off a row delete:
  the Flex sync deletes contracts missing from yesterday's report, including
  positions opened today.

## API

New `tags` and `tasks` routers under `/api/v1`. Strategy endpoints move off
`/tags` and `/tag-links`, which are then reserved for tags.

- `GET /tags?q=` returns tags with per-type usage counts. `POST /tags` returns the
  existing tag on a normalized match. `PATCH` renames or recolors a tag;
  `POST /tags/{id}/archive` archives it; `POST /tags/{id}/merge` merges it into
  another. Rename, merge, and archive are not exposed to agents.
- `POST /tag-links` / `DELETE /tag-links` attach or detach tags, singly or in
  bulk. Passing a tag name instead of an id creates the tag first.
- `GET /tags/search?all=&any=&none=&entity_type=` finds items by tag.
- `GET/POST/PATCH/DELETE /tasks` manage tasks, with filters for `status`, `tag`,
  `strategy_id`, `trade_group_id`, and `symbol`. `POST/DELETE /tasks/{id}/links`
  link and unlink items.
- Trade, position, and trade-group read endpoints include their tags and open
  task counts.

### MCP tools

Thin wrappers over the endpoints, in the existing MCP server:
`search_tags`, `create_tag`, `tag_items`, `untag_items`, `find_by_tags`,
`list_tasks`, `create_task`, `update_task`, `delete_task`, `link_task`,
`unlink_task`. No rename, merge, or archive tools.

## UI

- **Inline tagging.** A chip area on trade, position, trade group, and task rows with
  type-ahead: suggestions show usage counts, Enter creates a new tag, and × removes
  one. Agent-applied chips get a small marker.
- **Bulk tagging.** Select rows, then "Add tag…" / "Remove tag…".
- **Tags page.** Tag list with counts, rename, merge, color, and archive. Results
  are tabbed (Trades | Positions | Trade groups | Tasks) with all/any/exclude
  filters. No P&L or other aggregates.
- **Tasks page.** Its own nav entry. List filtered by status, tag, strategy, group, or symbol, with a
  one-click status change. Done tasks are hidden behind a toggle.
- **Linked surfaces.** Trade groups get a Tasks section. Position and trade rows
  get a task badge and a "+ task" shortcut.
- **Renames.** On the Trades page, the "Tags: Tagged / Untagged" filter becomes
  "Group: Grouped / Ungrouped" (`?group=`), and the "Tag Group" column becomes
  "Trade Group". `TradeTaggingPage.tsx` becomes `StrategiesPage.tsx`.

## Delivery

1. **Refactor PR (shipped).** Move strategies out of the tag tables, apply the
   API and UI renames, and drop the unused tag types. No behaviour change. The
   old `/tags`, `/themes`, and `/tag-links` routes were removed outright; the
   feature PR brings `/tags` and `/tag-links` back for free-form tags. The
   `tags` / `tag_links` tables are empty and keep their old columns until then.
2. **Feature PR.** Tags, tasks, sync hooks, API, MCP tools, and UI.

## Out of scope

Auto-tagging rules, reporting by tag (P&L, Greeks, aggregates), due dates,
assignees, reminders, manual task ordering, and tag inheritance between orders or
positions.
