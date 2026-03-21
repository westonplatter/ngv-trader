# Core UX Actions

Reusable interaction patterns for high-frequency operator workflows in ngv-trader.

## Purpose

- Standardize action UX across pages.
- Reduce accidental destructive actions.
- Keep fast paths fast for active trading workflows.

## Core Patterns

### 1) Safe Destructive Action (Inline Two-Step)

Use for row-level removals where context is visible (example: remove instrument from watch list).

- Step 1: user clicks neutral action (`Remove`).
- Step 2: inline confirm affordance appears (`Confirm`), visually dangerous.
- Step 3: on confirm, execute delete mutation.
- Step 4: refresh local/remote state and clear confirm state.

Rules:

- Confirm state is scoped to one row/item id.
- Confirm state auto-clears after success.
- Show loading state on confirm while request is in-flight.
- Do not allow multiple concurrent confirms for same row.

Recommended copy:

- Trigger: `Remove`
- Confirm: `Confirm`
- Busy: `Removing...`

### 2) Full-Entity Destructive Action (Dialog Confirm)

Use for deleting a container or entity with broad blast radius (example: delete watch list and all instruments).

- Use explicit confirmation text that names impact.
- Require an affirmative confirmation before API delete.
- After success: clear selected entity state, refresh list, and navigate to a safe fallback.

Recommended copy:

- `Delete this watch list and all its instruments?`

### 3) Non-Destructive Mutations (Single-Step)

Use one-click actions for safe operations (refresh, sync, edit mode, retry).

- Button should execute directly.
- Show in-flight state (`Refreshing...`, `Saving...`).
- Show inline success/error feedback near action.

Recommended variants:

- Inline stateful button: keep the action in place, switch label during mutation (`Save` -> `Saving...`), then show nearby success/error text.
- Persistent status line: show a small adjacent or below-action message such as `Saved 10:42:13` or `Save failed: HTTP 500`.

Preferred pattern for sidebar entity save actions:

- Keep primary action label stable at rest (`Save`).
- On click, disable repeat submission while pending.
- Change label to `Saving...` during the request.
- Show inline feedback directly under the action group after completion.
- Success copy should be short and confirm completion, ideally with a timestamp.
- Error copy should be human-readable and preserve context for retry.

Recommended copy:

- Idle: `Save`
- Busy: `Saving...`
- Success: `Saved 10:42:13`
- Error: `Save failed: HTTP 500`

## State Model

For any action component, keep these states explicit:

- `idle`
- `confirming` (for destructive flows)
- `pending`
- `success` (optional transient)
- `error`

Minimum state keys for destructive row actions:

- `confirmId: number | null`
- `pendingId: number | null`
- `error: string | null`

## Accessibility + Keyboard

- Confirm control must be keyboard-focusable and reachable in tab order.
- `Escape` should cancel inline confirm state when practical.
- Use clear labels, not icon-only destructive controls unless tooltip + aria-label are present.
- Preserve focus predictably after action completes.

## Error Handling

- Keep user on current page and preserve context on failure.
- Show human-readable inline error.
- Clear stale confirm state after failure only if retry would be unsafe; otherwise keep confirm visible for quick retry.

## Placement + Visual Priority

- Destructive trigger starts neutral.
- Confirm control uses danger color and stronger contrast.
- Keep confirm action adjacent to triggering row/item to preserve context.

## Reuse Checklist

Before implementing an action on any page:

- Is it destructive?
- What is the blast radius (row vs entity)?
- Should confirmation be inline two-step or dialog?
- What state keys are needed (`confirmId`, `pendingId`, `error`)?
- What refresh/invalidation is needed after success?
- What exact copy communicates impact?

## Current Reference

- `/watchlists`:
  - Row-level remove instrument: inline `Remove -> Confirm -> DELETE`.
  - Watch list delete: full-entity confirm dialog before `DELETE`.
- `/structures`:
  - Sidebar save: single-step `Save` action with `Saving...` pending state and inline success/error text directly below the actions.
