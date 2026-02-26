# Spec: Tradebot Contract Metadata Auto-Fetch

## Purpose

Ensure Tradebot handles contract metadata upkeep behind the scenes, while informing the user when metadata is being fetched for their request.

## Problem

- Users can request previews/submissions for symbols not yet present in `contracts`.
- Current UX can shift orchestration burden to the user (for example asking them to run `contracts.sync`).
- This creates friction and makes contract-cache maintenance a user concern.

## Scope

- Tradebot auto-detects missing contract metadata during contract lookup/order support flows.
- Tradebot enqueues metadata fetch jobs without requiring user action.
- Tradebot communicates that it is fetching metadata to support the request.
- Add background freshness scheduling to reduce cache misses.

## Non-goals

- Replacing current worker/job architecture.
- Eliminating all transient metadata misses.
- Adding real-time streaming contract metadata.

## UX Requirements

- When metadata is missing, Tradebot says it is fetching metadata now.
- Tradebot does not ask the user to manually run `contracts.sync`.
- Tradebot resumes request flow after fetch when possible.
- If fetch is still in progress, Tradebot returns an operator-friendly wait/retry message.

## Functional Plan

1. Add auto-fetch in lookup/order support path.
   - On missing `contracts` rows for `(symbol, sec_type)`, enqueue `contracts.sync` with resolved exchange/spec.
   - Avoid duplicate queue spam with idle/active job guard logic.
2. Include fetch status in tool responses.
   - Return structured status (for example `metadata_status=syncing`, `job_id` when available).
   - Include a concise user-facing message for the assistant to surface.
3. Update Tradebot instruction/prompt behavior.
   - Require announcing auto-fetch when triggered.
   - Prohibit asking users to orchestrate contract metadata jobs.
4. Keep order intent prompts focused.
   - Ask only trading-intent fields (account, quantity, order type, tif, etc.), not metadata maintenance steps.

## 5. Add Background Freshness

Schedule periodic `contracts.sync` for core symbols so misses are rare.

- Core set (initial): `CL`, `MCL`, `NG` (expandable).
- Frequency: periodic job enqueue from worker/scheduler path (for example every 15-60 minutes in market sessions).
- Guardrails:
  - Do not enqueue if same job type is already queued/running.
  - Use bounded specs list and stable client ID defaults.
  - Emit heartbeat/log visibility for freshness runs.
- Outcome:
  - Higher cache hit rate for contract lookup and order preview flows.
  - Fewer user-visible “metadata warming” events.

## Observability

- Track counts for:
  - auto-fetch triggers,
  - successful sync completions,
  - stale/missing metadata incidents,
  - background freshness runs.
- Log symbol/sec_type and job id for auto-fetch events.

## Rollout

1. Implement auto-fetch trigger + response fields.
2. Update assistant prompt/instructions.
3. Add periodic background freshness enqueue.
4. Validate with MCL/CL/NG request flows in chat.
5. Iterate frequency/symbol set from production behavior.

## Acceptance Criteria

- User can request contract info/order preview without manual metadata orchestration.
- When metadata fetch is required, Tradebot explicitly informs the user it is fetching metadata.
- Tradebot enqueues sync automatically and does not ask user to run `contracts.sync`.
- Periodic freshness jobs run for core symbols and reduce cold-cache misses.
