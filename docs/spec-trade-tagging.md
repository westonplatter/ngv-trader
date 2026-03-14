# Spec: Trade Strategies and Lifecycle Grouping

## Decision Authority

Trade Desk analyst perspective is primary for requirement decisions.  
When implementation tradeoffs are ambiguous, defer to what best supports desk workflow, lifecycle attribution, and PnL explainability.

## Trade Desk Analyst Final Direction (This Revision)

After quorum input from SWE, DBA, and UX, the Trade Desk Analyst selects:

1. Execution-level attribution is authoritative for PnL and lifecycle grouping.
2. Order-level linking is allowed only as an operator assist to find candidate executions.
3. V1 keeps relational tables with explicit constraints and indexes; no graph database.
4. Strategy attribution quality and explainability are prioritized over auto-link convenience.

## Problem

The desk needs to organize orders, trades, and executions into strategy-aligned lifecycle groupings across multiple accounts.  
Today, activity can originate from ngv-trader or outside workflows (for example phone trading), and must still roll up into coherent campaign-level PnL.

## Goals

1. Represent each strategy campaign from entry to final exit, including rolls and adjustments.
2. Support flexible tagging for strategy intent and risk context.
3. Allow manual post-trade association for activity executed outside ngv-trader.
4. Provide reliable PnL reporting by theme, strategy, and lifecycle grouping.
5. Keep V1 implementation simple enough for near-term production use by an agentic trade desk.

## Non-Goals (V1)

1. Perfect ontology for all future strategies.
2. Separate graph database introduction.
3. Full automation of tag assignment without human override.

## Desk Terminology

1. Theme: broad money-making concept (example: short volatility).
2. Strategy: concrete expression of a theme (example: backend vol long, frontend vol short, spread risk hedged).
3. Trade Group: one lifecycle instance of a strategy (entry, roll/adjustment, exit).  
   Note: use `Trade Group` instead of `Grouping`.

## Working Example

1. Open campaign:
   1. Long CL Dec 2026 65 Call
   2. Short CL Jul 2026 65 Call
   3. Spread hedge in Jul/Dec CL to reduce calendar risk
2. In May: roll Jul legs to Sep
3. Late June: close remaining structure

All related orders/trades/executions must map to one Trade Group, even if some executions were entered externally and linked later.

## Recommended Data Direction (V1)

Use PostgreSQL + SQLAlchemy relational schema with graph-like links, not a separate graph DB.

1. Core entities:
   1. `trade_groups`
   2. `tags` (typed)
2. Relationship entities:
   1. `tag_links` (polymorphic link to `orders`, `trades`, `trade_executions`, `trade_groups`)
   2. `trade_group_links` (parent/child lineage for roll chains and campaign relationships)
3. Mandatory attribution rules:
   1. Every execution belongs to exactly one Trade Group
   2. Every Trade Group has exactly one primary Strategy tag
   3. Execution-level attribution is authoritative; order-level reconciliation must resolve to executions before final assignment.
4. Provenance fields for auditability:
   1. `source` (`manual`, `rule`, `agent`)
   2. `created_by`
   3. `confidence`
   4. `assigned_at`

## DBA Constraints and Indexing Requirements (V1)

These are required for production-safe integrity and reporting performance.

1. `trade_groups`
   1. Canonical columns:
      1. `id` (pk)
      2. `account_id` (fk -> `accounts.id`, nullable; auto-populated from the first assigned execution's account when null; serves as default-filter anchor for reporting, not a membership boundary)
      3. `name` (text, not null)
      4. `notes` (text, nullable)
      5. `status` (text, not null; suggested values: `open`, `closed`, `archived`)
      6. `opened_at` (timestamptz, not null)
      7. `closed_at` (timestamptz, nullable)
      8. `created_at` (timestamptz, not null)
      9. `updated_at` (timestamptz, not null)
      10. Optional lifecycle metadata: `opened_by`, `closed_by` (nullable)
   1. Foreign key: `trade_groups.account_id -> accounts.id`
   1. Index: `(account_id, created_at desc)` for desk recency views
2. Execution-to-group assignment
   1. Use explicit mapping table (recommended name: `trade_group_executions`)
   2. Columns: `trade_group_id`, `trade_execution_id`, `source`, `created_by`, `confidence`, `assigned_at`
   3. Constraints:
      1. Foreign key `trade_group_id -> trade_groups.id`
      2. Foreign key `trade_execution_id -> trade_executions.id`
      3. Unique `(trade_execution_id)` to enforce exactly one Trade Group per execution
      4. Not null for `source`, `assigned_at`
   4. Indexes:
      1. `(trade_group_id, assigned_at desc)`
      2. `(trade_execution_id)` unique index (from the uniqueness rule)
   5. Assignment history table (required for audit + timeline):
      1. Recommended name: `trade_group_execution_events`
      2. Columns: `id` (pk), `trade_execution_id`, `from_trade_group_id` (nullable), `to_trade_group_id` (nullable), `event_type` (`assigned`, `reassigned`, `unassigned`), `source`, `created_by`, `confidence`, `reason`, `event_at`
      3. Rule: reassignment/unassignment must append an event row; do not lose prior state
      4. Indexes:
         1. `(trade_execution_id, event_at desc)`
         2. `(to_trade_group_id, event_at desc)`
3. `tags`
   1. Canonical columns:
      1. `id` (pk)
      2. `tag_type` (text, not null; allowed: `theme`, `strategy`, `risk_intent`, `hedge_type`, `holding_horizon`)
      3. `value` (text, not null)
      4. `normalized_value` (text, not null)
      5. `created_by` (text, not null)
      6. `created_at` (timestamptz, not null)
   2. Normalization rule:
      1. `normalized_value = lower(trim(value))`
      2. Collapse internal repeated whitespace to a single space before persistence
   3. Unique `(tag_type, normalized_value)` so duplicates cannot fragment reporting
   4. Index `(tag_type, normalized_value)` for typeahead and lookup
4. `tag_links`
   1. Canonical columns:
      1. `id` (pk)
      2. `entity_type` (text, not null; allowed: `orders`, `trades`, `trade_executions`, `trade_groups`)
      3. `entity_id` (bigint, not null)
      4. `tag_id` (fk -> `tags.id`, not null)
      5. `tag_type` (text, not null, denormalized copy of `tags.tag_type` for constraints/query speed)
      6. `is_primary` (bool, not null, default `false`)
      7. `source` (text, not null; `manual`, `rule`, `agent`)
      8. `created_by` (text, not null)
      9. `confidence` (numeric/float, nullable)
      10. `assigned_at` (timestamptz, not null)
      11. `created_at` (timestamptz, not null)
   2. Denormalization rule:
      1. `tag_links.tag_type` must equal `tags.tag_type` at insert/update time.
      2. `tags.tag_type` is immutable in V1 to prevent drift with existing links.
   3. Unique `(entity_type, entity_id, tag_id)` to prevent duplicate links
   4. Partial unique: one primary strategy per Trade Group
      1. Unique on `entity_id` where `entity_type='trade_groups'`, `tag_type='strategy'`, and `is_primary=true`
   5. Indexes:
      1. `(entity_type, entity_id)`
      2. `(tag_id, entity_type)`
5. `trade_group_links`
   1. Canonical columns:
      1. `id` (pk)
      2. `parent_trade_group_id` (fk -> `trade_groups.id`, not null)
      3. `child_trade_group_id` (fk -> `trade_groups.id`, not null)
      4. `link_type` (text, not null)
      5. `created_by` (text, not null)
      6. `created_at` (timestamptz, not null)
   2. `link_type` minimum required values in V1: `roll_from`
   3. Optional values that may be added in V1.1+: `adjustment_of`, `child_campaign`
   4. Unique `(parent_trade_group_id, child_trade_group_id, link_type)`
   5. Check `parent_trade_group_id <> child_trade_group_id`
   6. Cycle prevention is required at service layer and covered by validation tests

## Tag Types (Initial Controlled Vocabulary)

1. `theme` (optional at Trade Group level; multiple themes allowed)
2. `strategy` (required at Trade Group level; one primary)
3. `risk_intent` (example: reduce risk, transient delta)
4. `hedge_type` (example: spread hedge, vol hedge)
5. `holding_horizon` (intraday, overnight, swing)

## UX/Workflow Requirements

1. Default user action on new activity: attach to existing Trade Group or create a new one.
2. Fast tagging with quick-pick chips for common tags.
3. Suggested tags/groups from recent similar executions, including roll scenarios where a closing execution in one leg is paired with an opening execution in another leg. Suggestions must never auto-assign without user confirmation.
4. User can CRUD Strategy and Theme catalog items.
5. User can edit a Trade Group after creation (at minimum `name`, `notes`, `status`, `closed_at`).
6. Manual reassignment flow for externally placed trades.
7. Timeline view per Trade Group: entry, rolls/adjustments, exits.
8. Visible provenance badge (`manual`, `rule`, `agent`) and easy override.
9. Show confidence next to provenance for non-manual assignments.

## Reporting Requirements (V1)

Must support:

1. PnL by Theme
2. PnL by Strategy
3. PnL by Trade Group lifecycle
4. Hedge-adjusted vs gross PnL

## FastAPI API Surface (SWE Proposal, Trade Desk Approved)

All endpoints are under `/api/v1`.

1. Trade Groups
   1. `GET /trade-groups`
      1. Query: `account_id`, `status`, `strategy_tag`, `theme_tag`, `opened_from`, `opened_to`, `limit`
      2. Purpose: desk list view and filtering
   2. `POST /trade-groups`
      1. Body: `name`, `notes`, optional initial `strategy_tag_id`
      2. Purpose: create lifecycle container; `account_id` is not provided at creation — it is auto-populated from the first assigned execution's account
   3. `GET /trade-groups/{trade_group_id}`
      1. Purpose: detail view with tags, lifecycle state, and attribution summary
   4. `PATCH /trade-groups/{trade_group_id}`
      1. Body: mutable metadata (`name`, `notes`, `status`, `closed_at`)
      2. Purpose: lifecycle updates (open/closed/archived)
   5. `DELETE /trade-groups/{trade_group_id}`
      1. Purpose: delete group and free execution associations for reassignment
      2. Behavior:
         1. Remove `trade_group_executions` rows for the group
         2. Write corresponding `execution_unassigned` events to `trade_group_execution_events`
         3. Keep `trade_executions` and `trades` unchanged

2. Strategies (Catalog CRUD)
   1. `GET /strategies`
      1. Query: `q`, `limit`
      2. Purpose: list/search strategy catalog
   2. `POST /strategies`
      1. Body: `value`, `created_by`
      2. Behavior: creates `tags` row with `tag_type='strategy'`
   3. `PATCH /strategies/{strategy_id}`
      1. Body: mutable metadata (`value`)
      2. Behavior: updates strategy tag value with normalization rules
   4. `DELETE /strategies/{strategy_id}`
      1. Behavior: allowed only when no blocking references, or returns validation error

3. Themes (Catalog CRUD)
   1. `GET /themes`
      1. Query: `q`, `limit`
      2. Purpose: list/search theme catalog
   2. `POST /themes`
      1. Body: `value`, `created_by`
      2. Behavior: creates `tags` row with `tag_type='theme'`
   3. `PATCH /themes/{theme_id}`
      1. Body: mutable metadata (`value`)
      2. Behavior: updates theme tag value with normalization rules
   4. `DELETE /themes/{theme_id}`
      1. Behavior: allowed only when no blocking references, or returns validation error

4. Execution Attribution
   1. `POST /trade-groups/{trade_group_id}/executions:assign`
      1. Body: `execution_ids[]`, `source`, `created_by`, `confidence`, `reason`
      2. Behavior: idempotent assignment; reject if execution already belongs to another group unless `force_reassign=true`
      3. Cross-account assignments are allowed; assignment does not require `trade_group.account_id == trade_execution.account_id`.
   2. `POST /trade-groups/{trade_group_id}/executions:unassign`
      1. Body: `execution_ids[]`, `source`, `created_by`, `reason`
      2. Behavior: removes assignment with audit trail
   3. `POST /trade-executions/{execution_id}/trade-group:reassign`
      1. Body: `to_trade_group_id`, `source`, `created_by`, `confidence`, `reason`
      2. Purpose: manual correction flow for external trades
   4. `GET /trade-groups/{trade_group_id}/timeline`
      1. Purpose: ordered lifecycle events (entry, rolls, adjustments, exits, reassignments)

5. Tags and Tag Links
   1. `GET /tags`
      1. Query: `tag_type`, `q`, `limit`
      2. Purpose: typeahead/select2 UX
   2. `POST /tags`
      1. Body: `tag_type`, `value`, `created_by`
      2. Behavior: must use one of the controlled tag types defined in this spec
   3. `POST /tag-links`
      1. Body: `entity_type`, `entity_id`, `tag_id`, `is_primary`, `source`, `created_by`, `confidence`
      2. Behavior: enforce one primary `strategy` per Trade Group
   4. `DELETE /tag-links/{tag_link_id}`
      1. Purpose: remove incorrect link

6. Reporting
   1. `GET /reports/pnl/trade-groups`
      1. Query: `account_id`, `group_by` (`theme`, `strategy`, `trade_group`), `from`, `to`, `include_hedge_adjusted`
      2. Purpose: required V1 desk reporting outputs

7. API Guardrails
   1. All mutation endpoints persist provenance fields (`source`, `created_by`, `confidence`, `assigned_at`/`created_at`).
   2. Assignment endpoints enforce execution-level single-group ownership.
   3. Order-level identifiers may be accepted as lookup hints, but final writes target execution IDs.

## Timeline Data Model (Confirmed)

1. `GET /trade-groups/{trade_group_id}/timeline` is a computed read model, not a manually edited timeline table.
2. Timeline is built from:
   1. `trade_group_executions` + `trade_executions` for entry/exit/adjustment execution events
   2. `trade_group_links` for lifecycle lineage events (for example `roll_from`)
   3. `trade_group_execution_events` for assignment/reassignment/unassignment audit events
3. Response shape is a flat ordered list with event type discriminator.
   1. Response envelope:
      1. `trade_group_id`
      2. `events[]`
   2. Event fields:
      1. `event_id`
      2. `event_type` (`entry_execution`, `exit_execution`, `adjustment_execution`, `roll_linked`, `execution_reassigned_in`, `execution_reassigned_out`, `execution_unassigned`)
      3. `occurred_at`
      4. `execution_id` (nullable)
      5. `related_trade_group_id` (nullable; used for roll/reassignment cross-links)
      6. `summary`
      7. `provenance` (`source`, `created_by`, `confidence`)
      8. `metadata` (optional object for UI details)
4. Ordering is `occurred_at ASC`, tie-breaker `event_id ASC`.

## Implementation Quality Directive

1. Before implementation, review existing routers and services in `src/api/routers` and `src/services` and match established patterns.
2. New trade-tagging endpoints must align with current conventions:
   1. `/api/v1` route structure
   2. Pydantic request/response models and validation style
   3. SQLAlchemy query and transaction patterns used in current routers
   4. Error handling and status-code behavior consistent with existing APIs
3. Do not lower quality bar for speed. Implementation should be at least equal to current code quality for readability, safety, and maintainability.

## Architecture Choice Review

1. Graph relationships + tags: **Yes**
   1. Implement through relational link tables and lineage edges in Postgres.
2. Polymorphic tables (Rails style): **Yes, narrowly**
   1. Use polymorphism for link tables only.
   2. Keep core domain tables explicit and strongly constrained.
3. Other options: **Hybrid relational-graph model is preferred**
   1. Most practical fit for current stack and reporting reliability.

## Trade vs Trade Group Relationship (Confirmed)

1. `Trade -> TradeExecution` remains the broker-ingestion structure and is preserved.
2. Trade Group membership is recorded at `trade_executions` level (authoritative).
3. Trade-level association to Trade Groups is derived from its executions, not stored as a required direct foreign key in V1.
4. A single `trade` may span multiple Trade Groups in edge cases; this must be surfaced as a reconciliation warning for operator review.

## Trade Group Lifecycle and Deletion (Confirmed)

1. Allowed statuses: `open`, `closed`, `archived`.
2. Status transitions are intentionally flexible in V1 for a single-operator desk.
   1. A Trade Group may move between `open`, `closed`, and `archived` in any direction.
   2. No transition matrix is enforced in V1.
3. `closed_at` is optional metadata and may be set/cleared as the operator updates lifecycle state.
4. Archived groups are not immutable in V1; they may be edited or reactivated as needed.
5. Deleting a Trade Group is allowed and does not delete `trades`/`trade_executions`; it only removes group associations so executions can be associated with a different Trade Group.

## Decisions (Confirmed)

1. Trade Group membership is cross-account in V1.
   1. A Trade Group may contain activity from multiple accounts.
   2. `trade_groups.account_id` is nullable and auto-populated from the first assigned execution's account when null. It serves as a default-filter anchor for reporting, not a membership boundary. The user does not set it at creation time.
   3. Themes, strategies, and tags are reusable across accounts.
2. Theme assignment is optional and multi-valued at the Trade Group level.
3. A single execution can only be linked to one Trade Group.
4. For external/manual reconciliation:
   1. Trades/executions must be linked to a Trade Group.
   2. Every Trade Group must have a primary Strategy.
5. Tag selection UX must support a typeahead/select2-style flow:
   1. User types a few characters.
   2. UI suggests existing tags.
   3. User can select an existing tag or create a new one.
6. Manual/external reconciliation will match activity at the `trade_executions` or `orders` level using fields already present on those records.
   1. `orders` matches are candidate-only and must be resolved to concrete `trade_executions`.
   2. Final Trade Group membership is written only at `trade_executions` level.
7. Spread/combo attribution policy (Trade Desk Analyst lead):
   1. `combo_summary` and related `leg` executions must be assigned to the same Trade Group.
   2. Group-level PnL defaults to `combo_summary` economics when present to avoid leg-level double counting.
   3. Leg executions remain required for risk decomposition and audit detail.
   4. If spread-linked executions are split across Trade Groups, mark as reconciliation error and require manual fix before final reporting.
8. Trade-level grouping actions in UX may exist for speed, but must fan out to execution-level writes.
9. Trade Group status transitions are operator-controlled in V1 and can move freely between `open`, `closed`, and `archived`.
10. Trade Groups are editable after creation via `PATCH /trade-groups/{trade_group_id}` for lifecycle metadata updates.
11. Strategy and Theme catalog items are CRUD-managed in V1 (with validation on referenced deletes).
12. Deleting a Trade Group must free linked executions for reassignment and preserve audit events.

## Open Questions (Product-Owner Sign-Off)

1. Should `confidence` be normalized to a fixed numeric range (for example `0.0-1.0`) or a small enum?
2. Should optional `trade_group_links.link_type` values (`adjustment_of`, `child_campaign`) be included in initial V1 release or deferred to V1.1?

## Acceptance Criteria

1. User can create and assign Trade Groups for all executions.
2. User can edit an existing Trade Group after creation.
3. User can CRUD Strategy catalog items.
4. User can CRUD Theme catalog items.
5. User can tag groups and activity with controlled vocabulary tags.
6. User can manually attach externally sourced activity to Trade Groups.
7. System preserves attribution history and source provenance.
8. Desk can generate V1 PnL views by Theme, Strategy, Trade Group, and hedge-adjusted status.
