---
topics: ["frontend", "typescript", "react", "style", "conventions"]
code_dirs_or_files: ["frontend/src/", "frontend/eslint.config.js", "frontend/tsconfig.app.json"]
description: TypeScript and React conventions for frontend/ — where code goes, how pages fetch and hold state, what gets a test, and the checks a change must pass.
---

# Frontend Style

Conventions for `frontend/`. The Python counterpart is
[python-style.md](python-style.md); the checks are in
[validation.md](validation.md#frontend-checks). Read this before adding a page,
a shared helper, or a new way of talking to the API.

## Principles

1. **Strict TypeScript.** `tsconfig.app.json` turns on `strict`, unused locals and
   parameters, and `verbatimModuleSyntax`. No `any`, no `@ts-ignore`. An
   `eslint-disable` carries a comment saying why and what would remove it.
2. **Pure logic lives outside components.** Sorting, filtering, formatting, and
   P&L math go in `lib/` or `utils/` as plain functions with a `bun test`. There is
   no component-test harness, so anything worth asserting must be a function over
   plain data.
3. **One way to do each thing.** Before writing a helper, grep for it. Before
   adding a state pattern, use the one the matching section below names.
4. **Comments explain why, not what.** Name the bug or trade-off the code guards
   against, as the existing header comments do.

## Layout

```
frontend/src/
  main.tsx          entry; installs the demo API interceptor before render
  App.tsx           nav shell and route table
  navItems.ts       top-nav entries (own module so the nav invariant is testable)
  config.ts         API_BASE_URL
  components/       one React component per file, default export, PascalCase name
  contexts/         React context providers and their hooks
  hooks/            reusable React hooks that are not tied to one domain
  lib/              domain modules: API clients, SSE client, demo fixtures,
                    page logic extracted for testing
  utils/            domain-agnostic helpers: number and date formatting, linkify
  index.css         Tailwind import only
```

- `lib/` knows about ngv-trader entities (trade groups, tags, marks).
  `utils/` does not; a `utils/` function would make sense in any app.
- `lib/` and `utils/` never import from `components/`. Shared types move down,
  not components up.
- A page component is the component mounted by a route in `App.tsx`. Widgets
  shared by several pages (`TagChips`, `ComboboxInput`, `TradeGroupSearchSelect`)
  also live in `components/`.
- No per-component CSS files. Styling is Tailwind utility classes inline.

## Data access

- The API base is `API_BASE_URL` from `config.ts`. Never hardcode a host.
- Response types are declared once and imported, not redeclared per page.
- Throw on a non-2xx response and surface the backend `detail` string when there
  is one; callers set page-level `error` state from the thrown message.
- Live updates arrive over SSE through `useSSE(topic, onEvent)` in `lib/events.ts`.
  Load the REST snapshot first, then merge events into local state. See
  [api-ux-sse.md](../design/api-ux-sse.md).

## State

Pick the store by who needs to see the value:

| Value | Where | Why |
| --- | --- | --- |
| Filters, sort, selected id, "show details" | URL query params via `useSearchParams` with `{ replace: true }`; omit defaults | Refresh and shared links restore the view; history does not pile up |
| Pane widths and other per-device layout | `localStorage` (see `useResizableColumn`) | Layout is a property of the screen, not the user |
| Cross-device user settings (privacy mode, focus mode) | `/user-preferences/<key>` API | Follows the operator between machines |
| Everything else | `useState` in the component | Default |

- Derive instead of store. If a value can be computed from state already held,
  compute it in render or `useMemo`, do not mirror it in a second `useState`.
- A mount-time preference GET must not clobber a toggle the user made before it
  resolved. Guard with a "touched" ref as `StrategiesPage` does for focus mode.

## Adding a route

1. Add the component under `components/` and the `<Route>` in `App.tsx`.
2. Add the entry to `navItems.ts`. If the path is a prefix of another entry, set
   `end: true` on it; `navItems.test.ts` enforces this.
3. Add a fixture branch in `lib/demoApi.ts` for each new GET endpoint so
   `?demo=1` renders the page without a backend. See
   [commits-and-prs.md](commits-and-prs.md#ui-change-screenshots-optional).

## Formatting and privacy

- Money, strikes, percents, greeks, multipliers: `utils/number.ts`. Identifiers
  never go through these helpers so they never gain thousands separators.
- Privacy mode: read `usePrivacy()` and render dollar amounts through
  `PRIVACY_MASK` or `formatRelativeReturn`. See
  [user-preferences-privacy-mode.md](../design/user-preferences-privacy-mode.md).
- Interaction patterns for destructive and mutating actions are in
  [ux-actions.md](../design/ux-actions.md).

## Tests

- `bun test` runs `*.test.ts` under `src/` with no DOM. Test pure functions in
  `lib/` and `utils/`; keep React out of test imports.
- Anything that imports `plotly` or a component tree cannot be tested here, which
  is why `navItems.ts` and `lib/strategyPnl.ts` are separate modules.

## Dependencies

- `bun add` honors the 14-day release cooldown in `bunfig.toml`; see
  [python-style.md](python-style.md#dependencies).
- Prefer the platform (`fetch`, `URLSearchParams`, `Intl`) over a package.

## Verifying

From `frontend/`, before every push:

```bash
bun run typecheck && bun run lint && bun test && bun run build
```
