# Planning Spec Format and Template

Use this file as a template when writing a new planning spec.

The goal is to produce a spec that is:

1. explicit about the problem and desired outcome
2. clear about scope and non-goals
3. concrete enough to implement
4. easy for both humans and agents to review

## Instructions

When creating a new spec:

1. copy this structure into a new `docs/spec-*.md` file
2. replace every placeholder with feature-specific content
3. remove sections that truly do not apply
4. keep the language descriptive, not aspirational
5. prefer concrete behaviors over vague goals

When filling it in:

1. name the affected system boundaries
2. state what is changing and what is not changing
3. include user-facing behavior when relevant
4. include operational constraints when relevant
5. define acceptance criteria that can be validated

Avoid:

1. implementation-free slogans
2. hidden assumptions
3. mixing current-state documentation with future-state plans
4. file-by-file changelogs in the spec body

## Template

```md
# Spec: <Short Feature Name>

## Complexity: <1-5>

<Rate the implementation complexity from 1 (trivial config/dependency changes, no app code) to 5 (cross-cutting architectural change touching many systems). This helps prioritize and set expectations.>

## Purpose

<One short paragraph explaining why this work matters.>

## Problem

- <What is broken, missing, too manual, too slow, or too risky today?>
- <What user or system pain does this create?>
- <What evidence or examples make the problem concrete?>

## Scope

- <What this spec does cover>
- <What this spec does cover>
- <What this spec does cover>

## Non-goals

- <What this spec intentionally does not solve>
- <What remains out of scope for this phase>

## Current State

- <Brief description of how the system works today>
- <Relevant existing APIs, jobs, workers, tables, or UI surfaces>
- <Important constraints inherited from the current implementation>

## Desired Outcome

- <What the system should do after this change>
- <What the operator or end user should experience>
- <What reliability, safety, or performance improvement should exist>

## UX Requirements

- <User-visible behavior requirement>
- <User-visible behavior requirement>
- <Error or fallback behavior requirement>

## Functional Plan

1. <Major implementation step>
   - <Key detail or guardrail>
   - <Key detail or guardrail>
2. <Major implementation step>
   - <Key detail or guardrail>
3. <Major implementation step>
   - <Key detail or guardrail>

## Data Model and State Changes

- <New or changed tables, columns, payloads, events, or response fields>
- <How state transitions work>
- <Compatibility or migration notes>

## API / Worker / Service Changes

- <Endpoint additions or changes>
- <Worker or scheduler behavior>
- <Background job changes>
- <Read/write path expectations>

## Operational Considerations

- <Retries, idempotency, timeouts, queueing, batching, or rate limits>
- <Logging and monitoring expectations>
- <Deployment or rollback concerns>

## Risks

- <Main technical or product risk>
- <Main technical or product risk>
- <Unknowns requiring validation>

## Observability

- <Metrics to add or inspect>
- <Logs to emit>
- <States or failures that should be visible to operators>

## Rollout

1. <Phase or sequence step>
2. <Phase or sequence step>
3. <Validation step>
4. <Follow-up step if needed>

## Acceptance Criteria

- <Observable outcome that proves the feature works>
- <Observable outcome that proves the feature works>
- <Observable outcome that proves the feature works>

## Open Questions

- <Decision still pending>
- <Decision still pending>

## Related Files

- <Important existing files or modules likely to be touched>
- <Important existing files or modules likely to be touched>
```

## Notes for Humans and Agents

Use this checklist before finalizing a spec:

1. Is the problem specific enough that another engineer can understand why the work exists?
2. Are the non-goals clear enough to prevent scope creep?
3. Does the spec describe the current system before proposing change?
4. Are the rollout steps incremental and defensible?
5. Can the acceptance criteria be tested or observed without guesswork?
6. If data or API shapes change, does the spec say where and how?

If the spec is for a larger feature, add sections only when they add decision-making value, for example:

1. Security considerations
2. Performance constraints
3. Migration plan
4. Alternatives considered
5. Example requests and responses
