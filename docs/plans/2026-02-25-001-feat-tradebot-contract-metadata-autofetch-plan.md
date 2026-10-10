---
title: "feat: Tradebot contract metadata auto-fetch"
type: feat
status: partial
created: 2026-02-25
artifact_contract: ce-unified-plan/v1
artifact_readiness: draft
product_contract_source: migrated-spec
execution: code
depth: lightweight
---

# feat: Tradebot contract metadata auto-fetch

> **Implementation status (verified 2026-10-10): partial.** On-demand fetch
> works in informational flows: `lookup_contract` and `add_watch_list_instrument`
> fall back to an IBKR fetch on a cache miss (`find_contracts_with_fallback` in
> `src/services/contract_lookup.py`). **Not built:** contract resolution and a
> metadata status in `preview_order` (it builds the order input without a
> contract lookup), and scheduled background freshness. No scheduler enqueues
> `contracts.sync` today. `add_watch_list_instrument` still tells the user to
> "run a contracts sync first" on a miss, which R2 forbids.

## Goal Capsule

- **Objective:** Tradebot keeps contract metadata current behind the scenes and tells the user when it is fetching, instead of asking them to run `contracts.sync`.
- **Authority hierarchy:** The `contracts` table is the source of truth. The agent never imports `ib_async`; IBKR access goes through jobs or `find_contracts_with_fallback`.
- **Execution profile:** Preview-path auto-fetch + status fields → prompt update → background freshness.
- **Stop conditions:** Stop if auto-fetch would require replacing the worker/job architecture.
- **Tail ownership:** Standard repo flow; validate with CL/MCL/NG chat flows.

---

## Product Contract

### Summary

Close the remaining gap: auto-fetch in the order preview path with a structured status the assistant can surface, plus periodic freshness for core symbols so misses are rare.

### Problem Frame

Users request previews for symbols not yet in `contracts`. The current UX can push cache maintenance onto the user ("run `contracts.sync`"), which is friction and the wrong owner.

### Requirements

- R1. When metadata is missing, Tradebot says it is fetching metadata now.
- R2. Tradebot never asks the user to run `contracts.sync` or orchestrate metadata jobs.
- R3. Tradebot resumes the request after the fetch when possible; if the fetch is still running, it returns an operator-friendly wait/retry message.
- R4. Order-intent prompts ask only for trading fields (account, quantity, order type, TIF), never metadata steps.
- R5. Periodic freshness keeps core symbols (`CL`, `MCL`, `NG`, expandable) cached.

### Non-Goals

- Replacing the worker/job architecture.
- Eliminating every transient metadata miss.
- Real-time streaming contract metadata.

---

## Planning Contract

### Key Technical Decisions

KTD1. **Dedupe with `enqueue_job_if_idle`.** It already exists in `src/services/jobs.py`; use it instead of new guard logic so repeated misses do not spam the queue.

KTD2. **Structured status in tool responses.** Return `metadata_status` (e.g. `syncing`) and `job_id` when a fetch was enqueued, plus a short user-facing message.

KTD3. **Consider `contracts.sync_activated` for freshness.** CL and NG are already seeded in `activated_products` and that job maintains a 12-month window. Scheduling it (and seeding MCL) may cover R5 without a separate per-symbol `contracts.sync` loop. See [the activated products plan](2026-06-20-001-feat-activated-products-security-master-plan.md).

### Assumptions

- Freshness runs every 15–60 minutes during market sessions; tune from production behavior.

---

## Implementation Units

### U1. Auto-fetch in the preview path

**Requirements:** R1, R3

**Files:** `src/services/tradebot_agent.py` (`_tool_preview_order`, `_build_order_input_from_tool_args`), `src/services/contract_lookup.py`

**Approach:** On missing `contracts` rows for `(symbol, sec_type)`, enqueue `contracts.sync` with the resolved exchange/spec via KTD1, and return KTD2's status fields.

### U2. Prompt and message updates

**Requirements:** R1, R2, R4

**Files:** `src/services/tradebot_agent.py` (`_SYSTEM_PROMPT`, tool error messages)

**Approach:** Require announcing auto-fetch when triggered. Remove user-facing "run a contracts sync" wording, starting with the `add_watch_list_instrument` miss message.

### U3. Background freshness

**Requirements:** R5

**Approach:** Periodic enqueue for the core set (per KTD3). Skip if the same job type is queued or running; use a bounded spec list and stable client ID defaults; emit heartbeat/log lines per run.

### U4. Observability

**Approach:** Count auto-fetch triggers, completed syncs, stale/missing metadata incidents, and freshness runs. Log symbol, sec_type, and job id per auto-fetch.

---

## Verification Contract

| Gate          | Command                          | Applies to |
| ------------- | -------------------------------- | ---------- |
| Imports       | `uv run python scripts/check.py` | all        |
| Backend tests | `task test -- -k tradebot`       | U1, U2     |

Not command-shaped: run MCL/CL/NG preview and lookup flows in chat against a cold cache.

---

## Definition of Done

- A user can request contract info or an order preview without manual metadata orchestration.
- When a fetch is required, Tradebot says it is fetching metadata.
- Tradebot enqueues the sync itself and never asks the user to run `contracts.sync`.
- Periodic freshness runs for core symbols and reduces cold-cache misses.

---

## Risks & Dependencies

- No scheduler exists yet; U3 needs a home (worker loop or a dedicated scheduler).
- Freshness overlaps with `contracts.sync_activated`; pick one owner to avoid duplicate IBKR load.

---

## Open Questions

- Should U3 schedule `contracts.sync_activated` (KTD3) or per-symbol `contracts.sync`?

---

## Sources & Research

- `src/services/tradebot_agent.py`: `_tool_lookup_contract`, `_tool_add_watch_list_instrument`, `_tool_preview_order`, `_SYSTEM_PROMPT`.
- `src/services/contract_lookup.py`: `find_contracts_with_fallback`.
- `src/services/jobs.py`: `enqueue_job_if_idle`.
- `docs/tradebot-chatbot.md`.
- Migrated from `docs/spec-tradebot-contract-metadata-autofetch.md`.
