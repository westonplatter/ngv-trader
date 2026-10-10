---
title: "feat: Auto-tag suggestions for trade closures"
type: feat
status: proposed
created: 2026-06-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: draft
product_contract_source: migrated-spec
execution: code
depth: standard
---

# feat: Auto-tag suggestions for trade closures

> **Implementation status (verified 2026-10-10): not implemented.** No
> `tag_suggestions` table, suggestion job, or review API/UI exists. The
> primitives it builds on are live: `trade_groups`, `trade_group_executions`,
> `tags`, `tag_links`, `trade_group_links`. The assignment tables carry
> `source` and `confidence`, but nothing writes machine suggestions. Since this
> was written, the Tagging UI was renamed to Strategies (`/strategies`, still
> `TradeTaggingPage.tsx`), and `_open_lot_trade_groups` in
> `src/api/routers/positions.py` now answers "which group holds the open
> position this fill closes".

## Goal Capsule

- **Objective:** After each sync, propose reviewable assignments for closing and rolling fills into the trade group that holds the open position, so the common case becomes "confirm" instead of "search and assign".
- **Authority hierarchy:** Live membership (`trade_group_executions`, `tag_links`, `trade_group_links`) is the only source of truth. `tag_suggestions` is a queue and is never read for membership.
- **Execution profile:** Staging table + generator behind an on-demand trigger → review API + UI → auto-dispatch after Flex sync → roll detection.
- **Stop conditions:** Do not build roll handling (U5) until the same-group vs. child-group question is confirmed. Nothing auto-commits.
- **Tail ownership:** Standard repo flow; ship U1–U2 first and validate on real synced fills.

---

## Product Contract

### Summary

One staging table, one background job, a small read/accept/reject API, and a review inbox. Accept replays through the existing manual write paths.

### Problem Frame

- Closing and rolling fills arrive unassigned on every Flex sync and must be hand-attributed back to their group.
- The match is mechanical (same contract, opposing side, close lifecycle) but done by eye on `/trades`.
- A roll produces a close on one contract and an open on another; the operator must recognize and link both.
- With no staging surface, any automation would write live membership directly, which the desk does not want.

### Requirements

- R1. A sync with a closing fill matching an open group produces a `pending` suggestion with rationale and confidence; live membership is unchanged.
- R2. Accepting yields identical DB state to a manual assign + tag-link, including the assignment history event.
- R3. Rejecting removes the suggestion, and the same proposal does not reappear.
- R4. A detected roll produces one suggestion referencing both legs; accept assigns the close leg and creates the roll relationship.
- R5. Re-running generation creates no duplicate pending rows and never resurrects decided fills.
- R6. The inbox lists pending suggestions by confidence with a preview (target group, executions, inherited tags) and Accept / Edit / Reject actions.
- R7. Batch accept above an operator-chosen confidence, with the same preview first; per-suggestion failures do not abort the batch.
- R8. When a fill is decided by any path, other pending suggestions for it become `superseded`.

### Non-Goals

- Automatic, unreviewed assignment (auto-accept is a follow-up).
- Predicting strategy/theme tags; tags are inherited from the matched group.
- Changes to ingestion, dedup, or canonicalization.
- A historical backfill model beyond running the job over a date range.

---

## Planning Contract

### Key Technical Decisions

KTD1. **Reuse `_open_lot_trade_groups` for close matching.** It already does the signed open-lot walk with an outer join. Do not write a second matcher; see `docs/solutions/logic-errors/position-trade-group-chips-included-closed-lots.md` for why the naive version is wrong.

KTD2. **Accept goes through existing write paths** (`executions:assign`, tag-link creation, a roll-link creator), so invariants (one execution → one group, one primary strategy, history events) hold automatically.

KTD3. **Partial unique index on `(trade_execution_id, target_trade_group_id, kind) WHERE status='pending'`** makes generation idempotent.

KTD4. **Accept is transactional.** Assignment + tag links + roll link commit together; a conflict fails that one suggestion with a visible error.

### Data model

`tag_suggestions`: `id`, `kind` (`assign_close` | `roll_open`), `account_id`, `trade_execution_id`, `roll_partner_execution_id` (nullable), `target_trade_group_id`, `suggested_tag_ids` (JSON), `link_type` (nullable, `roll_from`), `confidence` `Numeric(4,3)`, `rationale`, `status` (`pending` | `accepted` | `rejected` | `superseded`), `source` (`agent`), `created_by`, `created_at`, `reviewed_by`, `reviewed_at`, `review_reason`. Indexes: KTD3, `(status, confidence DESC)`, `(account_id, created_at)`. FKs to `trade_executions` and `trade_groups` with `ON DELETE CASCADE`. Decided rows are retained for audit. Additive only.

---

## Implementation Units

### U1. Staging table and generator (on-demand only)

**Requirements:** R1, R5

**Files:** `alembic/versions/` (new), `src/models.py` (`TagSuggestion`), `src/services/tag_suggestions.py` (new), `src/workers/jobs.py` (`JOB_TYPE_TRADES_SUGGEST_TAGS`, `handle_trades_suggest_tags`)

**Approach:** For each closing, unassigned canonical execution, find candidate groups via KTD1 and write `assign_close` rows inheriting the group's primary strategy and theme tags. Confidence weighs exact `con_id`, quantity reconciliation, single vs. multiple candidates, and same account. Open/close lifecycle comes from `raw` (`openCloseIndicator` / `openClose` / `positionEffect`), normalized as in `src/api/routers/trades.py`. Pure read of live tables; writes only the staging table.

### U2. Review API and inbox

**Requirements:** R2, R3, R6, R7, R8

**Files:** `src/api/routers/tag_suggestions.py` (new), `frontend/src/components/TradeTaggingPage.tsx`, `frontend/src/components/TradesTable.tsx`

**Endpoints:**

- `GET /api/v1/tag-suggestions?status=&account_id=&min_confidence=`
- `POST /api/v1/tag-suggestions/{id}/accept` (optional target/tag override)
- `POST /api/v1/tag-suggestions/{id}/reject` (optional reason)
- `POST /api/v1/tag-suggestions:accept-batch?min_confidence=`
- `POST /api/v1/tag-suggestions/generate` (enqueue for a date range / account)

**Approach:** Per KTD2 and KTD4. Include empty and per-suggestion error states.

### U3. Auto-dispatch after Flex sync

**Requirements:** R1

**Files:** `src/services/trade_sync_flexquery.py`

**Approach:** Enqueue the job after aggregate recompute, scoped to executions the sync touched.

### U4. Observability

**Approach:** Per run: candidates scanned, created by kind, duplicates skipped, superseded. Per decision: who, what, resulting writes. Queue health: pending count and oldest age.

### U5. Roll detection (gated on Open Questions)

**Requirements:** R4

**Approach:** Pair a `Close` on `con_id` A with a near-simultaneous `Open` on B sharing `symbol` + `right` but differing in expiry and/or strike (combo rolls share `brokerageOrderID`). Emit `roll_open`, add a roll-link creator (internal helper or a public `trade_group_links` endpoint), and show a two-leg preview.

---

## Verification Contract

| Gate          | Command                                                          | Applies to |
| ------------- | ---------------------------------------------------------------- | ---------- |
| Migration     | `task migrate ENV=dev`                                           | U1         |
| Imports       | `uv run python scripts/check.py`                                 | all        |
| Backend tests | `task test -- -k tag_suggest`                                    | U1–U3, U5  |
| Frontend      | `bun run typecheck && bun run lint && bun test && bun run build` | U2         |

---

## Definition of Done

- R1–R5 hold; specifically, accept produces the same DB state as a manual assign, and rejected proposals stay gone.
- The inbox supports accept, edit, reject, and batch accept with previews.
- Generation runs automatically after Flex sync.

---

## Risks & Dependencies

- Multiple open groups on one `con_id` cause false matches; lower confidence and show all candidates.
- Roll pairing is heuristic; both legs are previewed and human-confirmed.
- Partial closes make "which group / how much" ambiguous; down-weight rather than guess.
- Staleness between generation and review is handled by `superseded` and transactional accept.

---

## Open Questions

- **Roll handling (blocks U5):** co-assign the new open leg into the same group, or a new child group linked via `roll_from`? Recommendation: same-group first, child-group opt-in later.
- Partial closes: suggest at reduced confidence, or withhold until a full-size match?
- Should batch accept include roll suggestions, or only `assign_close`?

---

## Sources & Research

- `src/api/routers/positions.py`: `_open_lot_trade_groups`.
- `src/api/routers/trade_groups.py`, `src/api/routers/tags.py`: write paths reused on accept.
- `docs/solutions/logic-errors/position-trade-group-chips-included-closed-lots.md`.
- `docs/plans/2026-08-07-001-refactor-tagging-to-strategies-plan.md`: Tagging → Strategies rename.
- Migrated from `docs/spec-auto-tag-suggestions.md`.
