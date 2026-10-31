---
topics: ["frontend", "refactor", "handoff"]
description: Handoff for the frontend maintainability refactor — what landed, the open PR stack, how each change was verified, and the remaining items with step-by-step instructions.
---

# Frontend refactor handoff (2026-10-31)

Written so a different engineer or model can continue without the original
conversation. Read [frontend-style.md](../contributing/frontend-style.md)
first; every rule below assumes it.

## Where things stand

The review produced 14 findings, F1 to F14. Status:

| ID  | Name                                   | Status                                        |
| --- | -------------------------------------- | --------------------------------------------- |
| F1  | Oversized page components              | Done for the four planned pages, PRs below    |
| F2  | Two data-access patterns               | Done via #325 (`lib/api.ts`)                  |
| F3  | Duplicated error helper                | Done via #325                                 |
| F4  | API types live in components           | Done, #326 (`src/types/`)                     |
| F5  | Lib imports from components            | Done, #326                                    |
| F6  | Duplicated formatters                  | Done, #326 (`utils/date.ts`)                  |
| F7  | Unclear `lib/` vs `utils/` split       | Done, documented in frontend-style.md         |
| F8  | No frontend conventions doc            | Done, #326                                    |
| F9  | Stale frontend README                  | Done, #326                                    |
| F10 | Untested in-component logic            | Done for the four split pages (via F1)        |
| F11 | Eager plotly bundle                    | Open, one-line change, see below              |
| F12 | Buttons without `type`                 | Partly done: every moved button has it        |
| F13 | Vite template leftovers                | Open                                          |
| F14 | Inconsistent color and button classes  | Open                                          |

### Open pull requests, in merge order

Each PR is stacked on the one above it. GitHub shows the predecessor's diff
inside a PR until the predecessor merges; the base is `main` for all of them
and retargets cleanly.

| PR   | Branch                              | What                                             |
| ---- | ----------------------------------- | ------------------------------------------------ |
| #329 | `refactor/f1-strategies-detail-state` | `useTradeGroupDetail`; 11 states become one hook |
| #330 | `refactor/f1-positions-split`       | `components/positions/`, `lib/positions/`        |
| #332 | `refactor/f1-trades-split`          | `components/trades/`, `lib/trades/`              |
| #333 | `refactor/f1-strategies-split`      | `components/strategies/`, `lib/strategies/`      |
| #334 | `refactor/f1-pricing-split`         | `components/pricing/`, `lib/pricing/`            |

Merged earlier: #326 (types, date utils, style guide), on top of #324 and
#325 which the repo owner landed in parallel.

**If `main` moves before these merge** (another frontend PR lands), rebase the
stack from the bottom:

```bash
git fetch origin main
git rebase --onto origin/main <old-tip-of-predecessor> refactor/f1-positions-split
# repeat for each branch above it, each onto the newly rebased predecessor
git push --force-with-lease -u origin <branch>
```

This happened once already (#326 squash-merged under #329); the rebase was
clean because each branch only adds files under its own folder.

## The pattern every split follows

```
components/<page>/
  <Page>Page.tsx     composition root: hooks in, panes out, under ~300 lines
  use<Concern>.ts    one hook per data concern; returns one object
  <Pane>.tsx         markup only; props in, callbacks out; never fetches
lib/<page>/
  <topic>.ts         pure functions over plain data
  <topic>.test.ts    bun test for each
types/<resource>.ts  API payload shapes, header names the backend model
```

Rules that kept the diffs safe, and that the next page should keep:

1. **Derive, don't clear.** When state belongs to a selection (a group id, an
   instrument), store it together with that key and derive the empty state
   when the key changes. This is how every `eslint-disable
   react-hooks/set-state-in-effect` was removed. See `useTradeGroupDetail`,
   `useTradeGroups`, `useInstrumentData`.
2. **Promise chains in effects, not `async/await`.** The React Compiler lint
   flags a `setState` reachable synchronously from an effect body. A `.then`
   callback is fine; an awaited call inside an async function called from the
   effect is not.
3. **Refs are written in effects, never during render.** `const ref =
   useRef(x); ref.current = x;` at the top of a hook is a lint error. Use
   `useEffect(() => { ref.current = x; }, [x])`.
4. **Pane-local state resets by remount.** Mount a detail pane with
   `key={id}` instead of adding reset effects. See `GroupDetailPane`.
5. **Copy JSX verbatim.** Class strings must not change, so the screenshot
   diff stays byte-identical. Only `type="button"` was added to buttons.

## How every change was verified

From `frontend/`:

```bash
bun run typecheck && bun run lint && bun test && bun run build
cd .. && uv run python scripts/docs_check.py   # whenever a doc changed
```

Plus a demo-mode screenshot diff. Start the dev server **from the frontend
directory inside the subshell** (the session's shell does not keep `cd`
between commands and `bun run dev` fails from the repo root with "Script not
found"):

```bash
(cd /home/user/ngv-trader/frontend && nohup bun run dev > /tmp/vite.log 2>&1 &)
# wait until: curl -s -o /dev/null -w "%{http_code}" http://localhost:5173/  -> 200
cd /home/user/ngv-trader/frontend
node scripts/screenshot.mjs "/positions?demo=1" before.png 2400 1000
# ... make the change ...
node scripts/screenshot.mjs "/positions?demo=1" after.png 2400 1000
cmp before.png after.png && echo identical
```

Take the "before" shot on the base commit (`git stash` works) and the "after"
on the change. Routes with fixtures: `/positions`, `/trades`,
`/strategies?trade_group_id=103` (also 105, and `strategy_id=1`),
`/structures` (empty state only; demo has no pricing fixtures).

Playwright is preinstalled; do not run `playwright install`. Use absolute
paths in shell commands; relative paths have resolved against the wrong
directory more than once in this session.

## Remaining items, with steps

Do them as separate small PRs off `main` (or stacked on #334 if it has not
merged, since F11 touches a file #334 creates). Conventional Commit titles,
the PR body sections from
[commits-and-prs.md](../contributing/commits-and-prs.md), and the four checks
before pushing.

### F11: lazy-load the pricing route

`components/pricing/PnlChart.tsx` is the only file importing plotly, and only
`components/pricing/PricingPage.tsx` imports it. In `src/App.tsx`:

1. Replace the static import with
   `const PricingPage = lazy(() => import("./components/pricing/PricingPage"));`
2. Wrap the `/structures` route element in
   `<Suspense fallback={<p className="text-gray-500">Loading...</p>}>`.
3. Confirm with `bun run build`: the main chunk should drop from about 5.4 MB
   to well under 1 MB, with plotly in its own chunk. Record both numbers in
   the PR body.
4. Screenshot diff on `/positions?demo=1` (unchanged) and `/structures?demo=1`
   (identical once loaded).

Optional second step: `plotly.js-basic-dist` instead of `plotly.js` would
shrink the chart chunk further, but it is a new dependency under the 14-day
cooldown; ask before adding it.

### F12: `type="button"` on the remaining buttons

Buttons in the five split folders already have it. Remaining files:
`MarketDataPage`, `WatchListsPage`, `TagsPage`, `TasksPage`, `OrdersTable`,
`OrdersSideTable`, `FlexQueryTokensTable`, `AccountsTable`,
`StrategyPnlTable`, `JobsTable`, `WorkerStatusLights`, `ComboboxInput`,
`TagChips`, `GroupTasks`, `TaskQuickAdd`, `TradeGroupSearchSelect`,
`App.tsx`. Find them with:

```bash
grep -rn "<button" frontend/src --include=*.tsx | grep -v 'type="button"'
```

Only `TradebotChat` has a real submit button inside a `<form>`; leave that
one. Screenshots stay byte-identical, so the diff is the verification.

### F13: Vite template leftovers

Delete `frontend/src/App.css` (empty), `frontend/src/assets/react.svg`
(unused), and decide on `frontend/public/vite.svg` (the favicon; `index.html`
references it). Replacing the favicon is a product choice; deleting the two
unused files is not. Run `bun run build` after.

### F14: shared class constants

Two concrete duplications, both low risk:

1. Positive P&L uses `text-green-700` in some places and `text-emerald-700`
   in others. Pick emerald (it is the majority) and change the green ones
   only where they mean P&L sign, not status badges. `grep -rn "text-green"
   frontend/src` lists them; most are messages, which should stay green.
2. The outline button class
   `whitespace-nowrap rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50`
   appears in several files. `TradesSyncControls.tsx` already hoists it to a
   `SYNC_BUTTON` constant; do the same per file or add
   `components/ui/buttonClasses.ts` with two or three named constants. Do not
   build a Button component; the style guide says Tailwind utilities inline.

Screenshot diffs will **not** be identical if any color changes; compare by
eye and say so in the PR.

### Not in the plan, but the next two largest files

`MarketDataPage.tsx` (678 lines) and `WatchListsPage.tsx` (592) were not in
the F1 plan. They follow the same recipe if wanted: hooks for data, panes for
markup, pure logic to `lib/`. Each would be one PR. Ask before starting; the
repo owner scoped F1 to the four pages above.

## Things that bit during this work

- The repo owner lands frontend PRs in parallel. Before starting anything,
  `git fetch origin main` and check whether the file you are about to touch
  changed on `main` (`git diff --name-only <merge-base> origin/main --
  frontend/`). Twice this session a PR did the same migration independently;
  the resolution was to take `main`'s version and re-apply only what was
  unique.
- `git merge-tree --write-tree origin/main HEAD` is a dry run for conflicts.
- Multi-file text edits were most reliable as a small Python script with
  exact-string asserts, run from the repo root with absolute paths. A
  mismatch aborts before anything is written.
- `bun test` runs `*.test.ts` only; nothing imports React or a component. Keep
  it that way unless the owner decides to add a DOM harness (a new
  dependency).
- The `markTime.test.ts` "single source of truth" test lists files that must
  call `formatMarkTime`. Moving such a file means updating that list; it was
  updated for the positions and strategies splits.
- `docs/design/*.md` front matter lists `code_dirs_or_files`. When a component
  file moves, update the path there and in any prose that names it, then run
  `uv run python scripts/docs_check.py`.
