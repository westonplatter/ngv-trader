# Spec: Tagging UX Separation (/tagging vs /trades)

## Problem

The current tagging UI tries to do too much in both places:

- `/tagging` (TradeTaggingPage) has a 3-column layout that includes a cramped Trades panel for assigning executions, competing for space with Strategy and Trade Group management.
- `/trades` (TradesTable) has an inline "Associate Trade To Trade Group" panel bolted onto expanded rows, with shared state that leaks across rows.

The result is two overlapping, half-complete workflows. Neither does its job well.

## Decision

Split responsibilities cleanly:

| Concern                                          | Owner Page                    | Rationale                           |
| ------------------------------------------------ | ----------------------------- | ----------------------------------- |
| Strategy CRUD                                    | `/tagging`                    | Low-frequency admin task            |
| Trade Group CRUD                                 | `/tagging`                    | Setup before operational use        |
| Trade Group management (status, notes, timeline) | `/tagging`                    | Group lifecycle is an admin concern |
| Browsing strategy > group hierarchy              | `/tagging`                    | Organizational overview             |
| Applying tags (assigning trades to groups)       | `/trades`                     | Operational, done while monitoring  |
| Creating a new group mid-workflow                | `/trades` links to `/tagging` | Redirect, not inline duplication    |

## Phase 1: Fix /trades inline tagging (do first)

Before removing any capability, ensure `/trades` can properly tag trades.

### 1a. Show assignment status on trade rows

The API already returns `is_assigned` and `assigned_trade_group_id` on each trade. TradesTable's frontend `Trade` interface does not include these fields and never renders them.

Changes:

- Add `is_assigned: boolean` and `assigned_trade_group_id: number | null` to the `Trade` interface in TradesTable.tsx.
- Add a new column (or badge in an existing column) showing assignment state:
  - Assigned: colored badge like `Group #42`
  - Unassigned: subtle "Untagged" label or empty

### 1b. Fix shared state bug in inline tagging

Currently, `strategyQuery`, `selectedStrategyId`, `tradeGroups`, `selectedTradeGroupId`, `associationMessage`, and `associationError` are component-level state shared across all expanded rows. If a user expands trade A, searches for a strategy, then collapses and expands trade B, the stale state persists.

Options (pick one):

- **Option A (simple):** Clear association state when `expandedTradeId` changes.
- **Option B (robust):** Move the association state into a per-row object keyed by trade ID.

Recommend Option A for now.

### 1c. Fix "Create Group In New Tab" link

The button at TradesTable line 442 opens `/tagging?account_id=...&prefill_group_name=...&strategy_id=...` but TradeTaggingPage ignores URL params entirely.

Changes:

- TradeTaggingPage reads `account_id`, `strategy_id`, `prefill_group_name` from `useSearchParams()`.
- Pre-selects the matching strategy and pre-fills the group creation form.

## Phase 2: Refocus /tagging on management

After Phase 1 confirms trades can be tagged from `/trades`:

### 2a. Remove the Trades column from /tagging

- Remove the entire right column (Trades table, filters, executions table).
- The page becomes a 2-column layout: Strategies | Trade Groups + Detail.
- The Trade Groups column gains more space for group management features.

### 2b. Enhance Trade Group management on /tagging

- Show group detail when selected: name, notes, status, opened_at, member executions count.
- Allow editing group metadata (PATCH endpoint already exists).
- Show timeline (currently hidden behind a comment on line 891).
- Allow status transitions (open/closed/archived).

### 2c. Move creation forms behind toggles

- Strategy and Trade Group creation forms are low-frequency actions.
- Hide behind a "+ New" button that expands the form inline (not a modal -- keep it simple).
- Reclaim list space for browsing.

## Phase 3: Polish /trades tagging UX (future)

### 3a. Compact action buttons

Replace verbose "Assign to #42" / "Unassign from #42" text with compact icon buttons (link/unlink icons) with tooltips. Recovers ~100px per row.

### 3b. Multi-select + bulk assign

Add checkboxes to trade rows. When selected, show a floating action bar: "Assign N trades to [Group Name]". The API already supports bulk execution ID arrays.

### 3c. Streamline the inline association panel

Simplify the 5-control inline panel (strategy input, Find Groups button, group dropdown, Associate button, Create Group button) to:

- Strategy dropdown (not autocomplete with manual "Find Groups" step)
- Trade Group dropdown (auto-loads when strategy selected)
- Assign button
- "New Group" link to `/tagging`

## Files Affected

- `frontend/src/components/TradesTable.tsx` -- Phase 1 (assignment status, state fix), Phase 3 (compact buttons, bulk assign)
- `frontend/src/components/TradeTaggingPage.tsx` -- Phase 1c (URL params), Phase 2 (remove trades, enhance management)
- `frontend/src/App.tsx` -- No changes expected

## Out of Scope

- Drag-and-drop assignment (interesting but adds complexity and a learning curve)
- Slide-over/modal for execution detail (no modal pattern exists in codebase yet)
- Removing `/tagging` from nav or merging pages
