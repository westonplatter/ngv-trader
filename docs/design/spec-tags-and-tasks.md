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
description: Spec for free-form tags on trades, positions, and tasks, plus a simple task list — moving strategies out of the tag tables, data model, sync hooks, API, MCP tools, and UI.
---

# Spec: Tags and Tasks

> **Status: NOT IMPLEMENTED.** Product decisions are settled. Open questions are
> listed at the end.

## Goal

- **Tags** are free-form, reusable labels a person applies to trades, positions,
  and tasks, such as `long-beta`, `risk-off`, and `offset-risk`. They describe an
  item; they do not group items.
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

## Background

The March 2026 tagging core built `tags` / `tag_links` as a generic catalog with
five `tag_type`s (`strategy`, `theme`, `risk_intent`, `hedge_type`,
`holding_horizon`). Only strategies were finished. Themes have API endpoints but
no UI, and the other three types were never surfaced. See
[strategies-and-trade-groups.md](strategies-and-trade-groups.md).

## Decisions

1. **A trade is the order** (`trades`), not the execution. Tagging an order
   covers all its fills.
2. **Live orders can be tagged** before settlement. The tag carries over when
   FlexQuery imports the order, using the same pattern as trade-group links.
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

## Data model

### Move strategies out of the tag tables

- New `strategies` table (`id`, `name`, `normalized_name`, `created_by`,
  `created_at`, `archived_at`), seeded from `tags` rows where
  `tag_type = 'strategy'`.
- New `trade_groups.strategy_id` FK, backfilled from primary strategy
  `tag_links`. It replaces the `uq_tag_links_primary_strategy_trade_group` index.
- Themes and the other three types become plain tags, or are dropped if they hold
  no data (open question 1).
- All of this is one reversible Alembic migration.

### Tags (repurposed `tags` / `tag_links`)

- `tags`: `id`, `value`, `normalized_value` (unique; case, spaces, `-`, and `_`
  folded), optional `color`, `created_by`, `created_at`, `archived_at`. The
  `tag_type` column goes away.
- `tag_links`: `tag_id`, `entity_type`, `entity_key`, `created_by`,
  `assigned_at`, `ended_at`. The `is_primary`, `tag_type`, and `confidence`
  columns go away.
- `entity_type` values: `trade`, `live_order`, `position`, `task`.
- `entity_key` identifies the item:
  - `trade` and `task`: the row id
  - `position`: `account_id` + `con_id`
  - `live_order`: `account_id` + broker order id
  - Typed nullable columns with a per-type check constraint, not a string key.
- Unique on (`tag_id`, entity) among rows where `ended_at` is null.

### Tasks

- `tasks`: `id`, `title`, `notes`, `status` (`todo` | `in_progress` | `done`),
  `created_by`, `created_at`, `updated_at`, `completed_at`.
- `task_links`: `task_id`, `entity_type` (`strategy`, `trade_group`, `position`,
  `trade`, `live_order`), typed key columns as above, `created_by`, `created_at`.
- Deleting a trade group or strategy drops its links, never the task.

## Sync hooks

- **Live order → settled trade.** After the FlexQuery trade sync, move
  `live_order` tag and task links onto the matching `trades` row and drop the
  live link. This mirrors `src/services/group_link_carryover.py`.
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
  another.
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
`search_tags`, `tag_items`, `untag_items`, `find_by_tags`, `list_tasks`,
`create_task`, `update_task`, `link_task`.

## UI

- **Inline tagging.** A chip area on trade, position, and task rows with
  type-ahead: suggestions show usage counts, Enter creates a new tag, and × removes
  one. Agent-applied chips get a small marker.
- **Bulk tagging.** Select rows, then "Add tag…" / "Remove tag…".
- **Tags page.** Tag list with counts, rename, merge, color, and archive. Results
  are tabbed (Trades | Positions | Tasks) with all/any/exclude filters, and the
  Trades tab has a count / net premium / realized P&L summary row.
- **Tasks page.** List filtered by status, tag, strategy, group, or symbol, with a
  one-click status change. Done tasks are hidden behind a toggle.
- **Linked surfaces.** Trade groups get a Tasks section. Position and trade rows
  get a task badge and a "+ task" shortcut.
- **Renames.** On the Trades page, the "Tags: Tagged / Untagged" filter becomes
  "Group: Grouped / Ungrouped" (`?group=`), and the "Tag Group" column becomes
  "Trade Group". `TradeTaggingPage.tsx` becomes `StrategiesPage.tsx`.

## Delivery

1. **Refactor PR.** Move strategies out of the tag tables, apply the API and UI
   renames, and drop the unused tag types. No behaviour change.
2. **Feature PR.** Tags, tasks, sync hooks, API, MCP tools, and UI.

## Out of scope

Auto-tagging rules, due dates, assignees, reminders, and tag inheritance between
orders or positions.

## Open questions

1. What data is in the old catalog? This decides whether themes and the other
   types are migrated into tags or dropped:
   `SELECT tag_type, count(*) FROM tags GROUP BY 1;`
   `SELECT entity_type, tag_type, count(*) FROM tag_links GROUP BY 1, 2;`
2. Does a live fill's order id match FlexQuery's `ibOrderID` for the same order,
   including combos? This decides the live-order key. Verify before building the
   carry-over.
3. Can agents merge, rename, and archive tags, or only create, attach, and
   detach? Default: create, attach, and detach only.
4. Does the Tasks list get its own nav page or a Portfolio panel? Default: its
   own page.
