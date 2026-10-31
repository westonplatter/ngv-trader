---
topics: ["tags", "tasks", "positions", "trades", "agent-tools", "frontend"]
code_dirs_or_files:
  [
    "src/services/item_links.py",
    "src/api/routers/tags.py",
    "src/api/routers/tasks.py",
    "src/services/group_link_carryover.py",
    "src/mcp/semantic_server.py",
    "frontend/src/components/TagsPage.tsx",
    "frontend/src/components/TasksPage.tsx",
    "frontend/src/components/TagChips.tsx",
  ]
description: Free-form tags on trades, positions, trade groups, and tasks, plus a simple task list — data model, how links survive sync, the API, MCP tools for local agents, and the UI.
---

# Tags and Tasks

- **Tags** are free-form, reusable labels — sticky notes like `long-beta`,
  `risk-off`, `offset-risk` — on trades, live (unsettled) orders, positions,
  trade groups, and tasks. They describe an item; they never group items and
  never feed reporting.
- **Tasks** are to-dos (To do → In progress → Done) linked to any mix of
  strategies, trade groups, positions, and trades, and can be tagged.
- A local LLM agent can do everything a person can through the same REST API,
  or the MCP tools that wrap it.

Strategies and trade groups are the verified structure reporting is built on
([strategies-and-trade-groups.md](strategies-and-trade-groups.md)). They never
use the word "tag".

## Rules

1. **A trade is the order** (`trades`), not the execution. Tagging an order
   covers all its fills.
2. **A live order is tagged per fill**, keyed by `ib_exec_id`. Order ids do not
   match across TWS and FlexQuery (see
   [trades-and-executions-sync.md](trades-and-executions-sync.md)), so the fill
   id is the only bridge. Tagging or linking a live fill fans out to every live
   fill of its order (same `permId`, else `orderId`, same account); a combo's
   summary and legs go together.
3. **A position is `(account_id, con_id)`**, never a `positions.id` — sync
   replaces those rows.
4. **No automatic tagging.** People, or agents acting on request, apply every tag.
5. **Provenance:** `created_by` is `user` or `agent:<name>`. The UI marks
   agent-applied chips and tasks with an `AI` badge.
6. **Tags are shared across accounts.** Names are matched after folding case,
   spaces, `-`, and `_` (`Long Beta` = `long_beta` = `long-beta`); the first
   spelling is kept for display.
7. **No reporting on tags.** No P&L, Greeks, or aggregates by tag.

## Data model

- `tags`: `value`, `normalized_value` (unique), optional `color`, `created_by`,
  `archived_at`.
- `tag_links` and `task_links` key each item with typed columns — `trade_id`,
  `trade_group_id`, `task_id` / `strategy_id`, `account_id` + `con_id` (position),
  `ib_exec_id` (live fill, with `account_id`/`con_id` denormalized) — enforced by
  a per-type check constraint. One link per (tag or task, item), via a partial
  unique index per entity type; for tags, among links that are not ended.
- `tag_links.ended_at` soft-ends a position tag (below).
- `tasks`: `title`, `notes`, `status`, `completed_at` (set on done, cleared on
  reopen).
- Deleting a trade, trade group, task, or strategy drops its links (FK cascade),
  never the task.

## Sync behavior

All in `src/services/item_links.py`.

- **Live fill → settled trade.** Each entry point in
  `src/services/group_link_carryover.py` also moves a live fill's tag and task
  links onto the settled fill's parent `trades` row, then drops the live links.
  So every settle path the trade-group carry-over covers — the intraday purge,
  the FlexQuery trade sync, and orphan reconciliation (`leg_strip`,
  `book_event`, and `bag_summary` fanning out to the settled legs) — moves them
  too. One trade collects the links of all its fills, deduplicated.
- **Late partial fills.** The intraday sync gives a new live fill the tags and
  tasks already on its order's other live fills. Within one TWS order only.
- **Position flat → tags end.** After the FlexQuery position sync and the
  intraday sync, an open position tag gets `ended_at` once the contract is absent
  (or zero) in both `positions` and `live_positions` **and** the account's
  settled snapshot (`positions.as_of_date`) is dated on or after the day the tag
  was applied. The date check matters: the Flex sync drops contracts missing
  from the T-1 report, including positions opened today, so a row's absence
  alone proves nothing. Ended tags are hidden in the UI and returned by search
  with `include_ended`. Re-tagging a reopened position opens a new link.
  An account that goes fully flat is handled by the Flex position sync: when the
  report has the account's statement with an empty `OpenPositions` section, it
  clears the account's rows and ends its tags, dated by the statement's
  `toDate`. A missing statement or section changes nothing.
- **Task links never end.** A task linked to a closed position keeps the link;
  the UI shows the position as closed.

## API

Routers `src/api/routers/tags.py` and `src/api/routers/tasks.py`.

| Endpoint                                                                     | Notes                                                             |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `GET /tags?q=&include_archived=`                                             | Most-used first; `usage` counts open links per entity type        |
| `POST /tags`                                                                 | Returns the existing tag on a normalized match                    |
| `PATCH /tags/{id}`                                                           | Rename (409 if it collides — merge instead) or recolor            |
| `POST /tags/{id}/archive`, `/unarchive`                                      |                                                                   |
| `POST /tags/{id}/merge`                                                      | Moves all links onto `into_tag_id`, then deletes the tag          |
| `POST /tag-links`, `DELETE /tag-links`                                       | `{tags: [id or name], items: [...]}`; names are created on attach |
| `GET /tags/search?all=&any=&none=&entity_type=`                              | Repeated params or comma lists; labels and tags only, no figures  |
| `GET /tasks?status=&include_done=&tag=&strategy_id=&trade_group_id=&symbol=` | Newest first; done hidden unless asked                            |
| `POST /tasks`, `GET/PATCH/DELETE /tasks/{id}`                                | Create takes `links` and `tags`                                   |
| `POST /tasks/{id}/links`, `DELETE /tasks/{id}/links`                         |                                                                   |

An item is `{"entity_type": ..., ...key}`: `id` for `trade`, `trade_group`,
`task`, `strategy`; `account_id` + `con_id` for `position`; `ib_exec_id` for
`live_execution`.

`GET /trade-executions`, `GET /positions`, and `GET /trade-groups` (list and
detail) return `tags` and `open_task_count` per row. On the trades read, a
settled row carries its trade's tags and an unsettled row its own fill's.

## MCP tools

In `src/mcp/semantic_server.py`, as thin wrappers over the REST API (not the
server's read-only DB connection): `search_tags`, `create_tag`, `tag_items`,
`untag_items`, `find_by_tags`, `list_tasks`, `create_task`, `update_task`,
`delete_task`, `link_task`, `unlink_task`. Writes are recorded as
`agent:<NGV_AGENT_NAME>` (default `local-llm`); the API base is `NGV_API_URL`
(default `http://localhost:8000/api/v1`). Renaming, merging, and archiving tags
is human-only, so there are no tools for it.

## UI

- **Inline chips** (`TagChips.tsx`) on Trades and Positions rows, trade-group
  detail, and tasks: type-ahead with usage counts, Enter creates, × removes.
  Trade-group list rows show their chips read-only.
- **Bulk tagging** on the Trades page: per-order checkboxes, then "Add tag" /
  "Remove tag".
- **Tags page** (`/tags`): catalog with rename, color, merge, archive; results
  tabbed Trades (settled and unsettled) | Positions | Trade groups | Tasks, with
  all / any / exclude filters in the URL.
- **Tasks page** (`/tasks`): filters for status, tag, symbol, strategy, and
  group; one-click status change; done behind a toggle.
- **Linked surfaces:** a Tasks section in trade-group detail; a task badge and
  "+ task" shortcut on Trades and Positions rows.

## Demo mode

`frontend/src/lib/demoTags.ts` holds tag and task fixtures built on the existing
demo positions, trades, and groups, and `demoApi.ts` serves `/tags`,
`/tags/search` (same all / any / none rules), and `/tasks`, and adds tags and task
counts to positions, trades, and trade groups. The story: `long-beta` cuts across
NQ, MES, and ES rows in three different trade groups (one of them an unsettled
live fill); `offset-risk` was applied by an agent.

| Screenshot                                                                                                                           | Route (`?demo=1`)                                                 |
| ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------- |
| [tags-search.png](https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/tags-and-tasks/tags-search.png)       | `/tags?all=long-beta` — one tag across three groups               |
| [tags-exclude.png](https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/tags-and-tasks/tags-exclude.png)     | `/tags?any=long-beta,risk-off&none=offset-risk&tab=positions`     |
| [positions-tags.png](https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/tags-and-tasks/positions-tags.png) | `/positions` — chips, task badges, the `AI` marker                |
| [tasks.png](https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/tags-and-tasks/tasks.png)                   | `/tasks`                                                          |
| [tags-flow.gif](https://raw.githubusercontent.com/westonplatter/ngv-trader/media/screenshots/tags-and-tasks/tags-flow.gif)           | Positions → Tags search → Tasks (8 s); demo writes do not persist |

## Follow-up work

Not done yet; noted while building and testing this feature.

### Found while building

- **Non-primary strategy links** were not migrated when strategies moved out of
  the tag tables; the UI never wrote any.
- **Tag search scales in Python.** `GET /tags/search` loads every open link and
  filters in memory — fine for one desk, revisit if links reach the tens of
  thousands.
- **Prettier drift** in `frontend/src/contexts/PrivacyContext.tsx`,
  `frontend/src/hooks/useResizableColumn.ts`, and `frontend/README.md` predates
  this work.

## Out of scope

Auto-tagging rules, reporting by tag, due dates, assignees, reminders, manual
task ordering, and tag inheritance between orders or positions.
