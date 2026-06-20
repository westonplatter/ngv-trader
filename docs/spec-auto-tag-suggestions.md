# Spec: Auto-Tag Suggestions for Trade Closures

> **Status: PROPOSED — not implemented (as of 2026-06-18).** No
> `tag_suggestions` table, suggestion job, or review API/UI exists yet. The
> tagging primitives this spec builds on (`trade_groups`,
> `trade_group_executions`, `tags`, `tag_links`, `trade_group_links`) are
> live; the `source="agent"` and `confidence` fields already exist on the
> assignment tables but nothing writes machine suggestions today. This spec is
> the plan to add a human-reviewed suggestion layer on top of them.

## Complexity: 3

One new table, one new background job, a small read/accept/reject API, and a
review UI panel. No changes to the broker sync path beyond dispatching a new
job at the end of it. Complexity comes from the matching heuristics and the
need to keep suggestions strictly isolated from live membership, not from
architectural surface area.

## Purpose

When the desk syncs executed trades, a new fill frequently closes — or rolls —
a position that already lives inside a tagged trade group. Today an operator
must manually find that group and re-assign the closing fill. This spec adds a
system that proposes those assignments (and their inherited tags) as reviewable
suggestions, so the common case becomes "confirm" instead of "search and
assign", while keeping a human in the loop for every change.

## Problem

- Closing and rolling fills arrive untagged on every Flex sync and must be
  hand-attributed back to the trade group that holds the open position.
- The matching is mechanical (same contract, opposing side, close lifecycle)
  but currently done by a human eyeballing `/trades`.
- Rolls are worse: a single roll produces a close on one contract and an open
  on a related contract, and the operator has to recognize and link both legs.
- There is no staging surface, so any automation today would have to write
  live membership directly — unacceptable given the desk wants review before
  anything moves.

## Scope

- A staging table for machine-generated tag/assignment suggestions.
- A background job that generates suggestions after each trade sync, plus an
  on-demand trigger.
- Matching logic for two suggestion kinds: closing an exact-contract position,
  and detecting an options roll.
- Read/accept/reject API that replays accepted suggestions through the
  existing assignment, tag-link, and roll-link write paths.
- A review UI that previews each suggestion with its rationale and confidence,
  and lets the operator accept, edit, or reject.

## Non-goals

- No automatic, unreviewed assignment. Nothing mutates live membership without
  an explicit accept (auto-accept thresholds are a deferred follow-up).
- No new strategy/theme inference. Suggested tags are inherited from the
  matched group, not predicted from scratch.
- No change to how trades/executions are ingested, deduplicated, or made
  canonical.
- No backfill model for historical untagged fills beyond running the same job
  over a date range.

## Current State

- Executions are ingested via FlexQuery (`src/services/trade_sync_flexquery.py`,
  TWS path dormant). Each canonical `trade_executions` row carries `con_id`,
  `side`, `quantity`, `executed_at`, `exec_role`
  (`standalone`/`leg`/`combo_summary`), and a `raw` JSON payload.
- Open vs close lifecycle is recoverable from `raw` via
  `openCloseIndicator` / `openClose` / `positionEffect`, normalized the same
  way `src/api/routers/trades.py:223` does it.
- Contract details (symbol, `strike`, `right`, `contract_expiry`, multiplier)
  live in `contracts` / `ContractRef` keyed by `(account_id, con_id)`.
- Tagging today: `trade_groups` are lifecycle containers; membership is
  execution-level via `trade_group_executions` (one execution → one group);
  `tags` + `tag_links` attach strategy/theme metadata; `trade_group_links`
  models roll relationships (`link_type IN ('roll_from','adjustment_of',
  'child_campaign')`) but has no public creation endpoint or UI.
- The assignment tables already carry `source` (`manual`/`rule`/`agent`) and a
  `confidence` numeric, so provenance for machine suggestions is already
  modeled — it is simply unused.
- Assignment endpoints (`trade_groups.py`) write membership immediately; there
  is no pending/suggested state.

## Desired Outcome

- After a sync, the operator sees a queue of suggestions like: "BUY 2 CL
  20261218 P70 (Close) appears to close the short put in group #42 'CL
  short-vol Q4'; inherit tags [short-put, income]; confidence 0.92."
- Accepting a suggestion produces exactly the same database state as if the
  operator had manually assigned the execution and applied the tags.
- Roll suggestions surface both legs and, on accept, create the
  `roll_from` link between the groups (or co-assign the open leg, per the
  resolved open question below).
- No live membership or tag link is ever created or modified without an
  explicit human accept.
- Re-running the generator never duplicates suggestions or re-proposes an
  already-decided fill.

## UX Requirements

- A review inbox lists pending suggestions, highest confidence first, with a
  human-readable rationale per row.
- Each suggestion previews the resulting change before commit: target group,
  the execution(s) involved, and the tags that would be inherited.
- Actions per suggestion: **Accept**, **Edit** (change target group or tags
  before accepting), **Reject** (with optional reason).
- A batch affordance to accept all suggestions above a confidence the operator
  picks, with the same preview shown first.
- Rejecting a suggestion removes it from the queue and prevents the same fill
  from re-surfacing the identical proposal on the next run.
- Empty state and a per-suggestion error state when an accept fails (for
  example, the execution was assigned elsewhere in the meantime).

## Functional Plan

1. Add a `tag_suggestions` staging table (see Data Model). It holds proposals
   only; it is never read as a source of truth for membership.
2. Add a suggestion generator service `src/services/tag_suggestions.py`.
   - Input: a set of newly canonical, currently-unassigned closing executions
     (and their roll-partner opens).
   - Output: `tag_suggestions` rows in `status='pending'`.
   - Pure read against live tables; writes only the staging table.
3. Matching — closing an exact-contract position (Phase 1).
   - For each closing execution on `con_id = X` not already in a group, find
     trade groups whose current `trade_group_executions` include opposing-side
     fills on the same `con_id = X` with a net non-zero position.
   - Propose `kind='assign_close'`: assign the closing fill to that group and
     inherit the group's primary strategy + theme tags.
   - Confidence is driven by exact `con_id` match, quantity reconciliation
     (does the close size match the group's open size), single-candidate vs
     multiple-candidate groups, and same `account_id`.
4. Matching — options roll detection (Phase 2).
   - Detect a `Close` on `con_id = A` paired with a near-simultaneous `Open`
     on `con_id = B` where B shares `symbol` + `right` with A but differs in
     `contract_expiry` and/or `strike` (combo rolls share `brokerageOrderID`).
   - Propose `kind='roll_open'` referencing the group that holds A: assign the
     close leg to that group, and either co-assign the open leg or create a
     roll-linked child group (per Open Questions).
5. Generation triggers.
   - Dispatch a `JOB_TYPE_TRADES_SUGGEST_TAGS` job at the end of a successful
     Flex sync, scoped to the executions that sync touched.
   - Expose an on-demand trigger (endpoint) for a date range / account.
6. Review and commit.
   - `accept` replays the suggestion through existing write paths:
     `executions:assign`, `tag_links` creation, and (rolls) a new roll-link
     creator. The staging row moves to `status='accepted'`.
   - `reject` moves the row to `status='rejected'` with an optional reason.
   - When a fill is decided (accepted or assigned manually elsewhere), any
     other pending suggestion for it is marked `status='superseded'`.

## Data Model and State Changes

New table `tag_suggestions`:

- `id`
- `kind` — `'assign_close' | 'roll_open'` (extensible)
- `account_id` — denormalized for filtering
- `trade_execution_id` — the primary fill being proposed for tagging
- `roll_partner_execution_id` — nullable, the open leg for `roll_open`
- `target_trade_group_id` — the group the suggestion attributes to
- `suggested_tag_ids` — JSON array of `tags.id` to inherit
- `link_type` — nullable, `'roll_from'` for roll suggestions
- `confidence` — Numeric(4,3), 0.0–1.0
- `rationale` — text, human-readable explanation rendered in the UI
- `status` — `'pending' | 'accepted' | 'rejected' | 'superseded'`
- `source` — `'agent'` (constant for now)
- `created_by`, `created_at`, `reviewed_by`, `reviewed_at`, `review_reason`

Constraints and indexes:

- Partial unique index on `(trade_execution_id, target_trade_group_id, kind)`
  where `status='pending'` — idempotent re-generation, no duplicate pending
  proposals for the same fill→group pairing.
- Index on `(status, confidence DESC)` for the review queue.
- Index on `(account_id, created_at)`.
- FKs to `trade_executions`, `trade_groups`, with `ON DELETE CASCADE` so the
  staging table never dangles.

State transitions: `pending → accepted` (commit replayed), `pending →
rejected` (operator declines), `pending → superseded` (the fill was decided by
another path). Accepted/rejected/superseded rows are retained for audit, not
deleted.

Compatibility: additive only. No existing table or column changes. Live
membership semantics are untouched because nothing reads `tag_suggestions` for
membership — it is strictly a queue.

## API / Worker / Service Changes

- New worker job `JOB_TYPE_TRADES_SUGGEST_TAGS` with handler
  `handle_trades_suggest_tags` in `src/workers/jobs.py`; dispatched at the end
  of `trade_sync_flexquery` after `_recompute_trade_aggregates`.
- New service `src/services/tag_suggestions.py` holding matching/scoring; pure
  read of live tables, writes only `tag_suggestions`.
- New router (e.g. `src/api/routers/tag_suggestions.py`):
  - `GET /api/v1/tag-suggestions?status=pending&account_id=&min_confidence=`
  - `POST /api/v1/tag-suggestions/{id}/accept` (optional body to override
    target group / tags before commit)
  - `POST /api/v1/tag-suggestions/{id}/reject` (optional reason)
  - `POST /api/v1/tag-suggestions:accept-batch?min_confidence=`
  - `POST /api/v1/tag-suggestions/generate` (on-demand, enqueues the job for a
    date range / account)
- A roll-link creator is needed for `roll_open` accepts; it can be a small
  internal helper or a public `trade_group_links` endpoint surfacing the
  existing model.
- Read/write path expectation: `accept` does not write membership directly —
  it calls the same assignment/tag-link logic the manual UI uses, so all
  existing invariants (one execution → one group, one primary strategy per
  group, history events) are preserved automatically.

## Operational Considerations

- Idempotency: generation upserts against the partial unique index; re-running
  over the same executions is a no-op for already-pending proposals.
- The generator must skip executions already in a group and already-decided
  fills, so repeated syncs do not resurrect rejected proposals.
- Accept is transactional: assignment + tag links + roll link commit together
  or not at all; on conflict (fill assigned elsewhere mid-review) it fails the
  single suggestion and surfaces the error rather than partially applying.
- Batch accept iterates per-suggestion so one failure does not abort the rest.
- Logging mirrors `flex_sync_log` style: per-run counts of candidates scanned,
  suggestions created, superseded.

## Risks

- False matches when multiple open groups hold the same `con_id`; mitigated by
  lower confidence, surfacing all candidates, and never auto-committing.
- Roll detection is heuristic (time proximity + symbol/right + expiry shift);
  wrong pairings are possible, which is exactly why both legs are previewed
  and human-confirmed.
- Quantity mismatches (partial closes, scaling) can make "which group" or "how
  much" ambiguous; Phase 1 should down-weight confidence rather than guess.
- Staleness between generation and review (the fill gets assigned manually) —
  handled by the supersede transition and transactional accept.

## Observability

- Per-generation-run metrics: candidates scanned, suggestions created by kind,
  duplicates skipped, superseded.
- Per-decision logging: accept/reject/supersede with `reviewed_by` and the
  resulting group/tag writes.
- Queue health: count of pending suggestions and age of oldest pending, so a
  growing untriaged backlog is visible.

## Rollout

1. Ship the `tag_suggestions` migration and the generator + job behind the
   on-demand trigger only (no auto-dispatch), validate suggestions read
   correctly without committing anything.
2. Add the read/accept/reject API and the review UI panel; exercise
   `assign_close` end-to-end on real synced fills.
3. Enable auto-dispatch at the end of Flex sync.
4. Add `roll_open` detection, the roll-link creator, and the two-leg preview.
5. Follow-up: optional confidence-threshold auto-accept and accept/reject
   learning.

## Acceptance Criteria

- After a sync that includes a closing fill matching an open tagged group, a
  `pending` suggestion exists with a populated rationale and non-null
  confidence, and live membership is unchanged.
- Accepting that suggestion yields identical DB state to a manual assign +
  tag-link of the same fill, including an assignment history event.
- Rejecting a suggestion removes it from the queue and the same proposal does
  not reappear on the next generation run.
- A detected roll produces a single suggestion referencing both legs; on
  accept, the close leg is assigned and a `roll_from` link is created.
- Re-running generation over the same executions creates no duplicate pending
  rows.

## Open Questions

- Roll handling: when a roll is accepted, should the new opening leg be
  co-assigned into the **same** group as the closed position, or placed in a
  **new child group** linked via `roll_from`? The model supports both;
  same-group is simpler operationally, child-group preserves per-expiry
  lifecycle. Recommendation: same-group for Phase 2, child-group as an opt-in
  later. **Needs confirmation before building Phase 2.**
- Should partial closes (close quantity < group open quantity) be suggested at
  reduced confidence, or withheld until a full-size match is found?
- Should `accept-batch` apply roll suggestions, or restrict batch to
  `assign_close` only for safety?

## Related Files

- `src/models.py` — add `TagSuggestion`; existing `TradeGroup`,
  `TradeGroupExecution`, `Tag`, `TagLink`, `TradeGroupLink`, `ContractRef`.
- `src/services/trade_sync_flexquery.py` — dispatch the suggestion job
  post-sync.
- `src/services/tag_suggestions.py` — new matching/scoring service.
- `src/workers/jobs.py` — new job type and handler.
- `src/api/routers/tag_suggestions.py` — new review API.
- `src/api/routers/trade_groups.py`, `src/api/routers/tags.py` — existing
  assignment and tag-link write paths reused on accept.
- `frontend/src/components/TradeTaggingPage.tsx`,
  `frontend/src/components/TradesTable.tsx` — host the review inbox.
- `alembic/versions/` — new migration for `tag_suggestions`.
