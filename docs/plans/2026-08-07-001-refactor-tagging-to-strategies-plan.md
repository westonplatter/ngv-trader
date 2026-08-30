---
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
execution: code
product_contract_source: ce-plan-bootstrap
type: refactor
created: 2026-08-07
depth: lightweight
---

# refactor: Rename "Tagging" to "Strategies" in UI and URLs

## Context

The Trade Tagging page is the operator's strategy workspace: the left column lists
strategies, the middle column lists that strategy's trade groups, the right column
shows group detail. "Tagging" describes the mechanism (tag rows in `tags` /
`tag_links`), not what the operator is doing there. The nav label, page heading, and
`/tagging` URL all lead with the mechanism, which reads as an implementation detail
in the one place the operator spends the most time.

Intended outcome: nav reads **Strategies**, the page heading reads **Strategies**,
and the route is `/strategies`. The domain vocabulary underneath — tags, tag links,
trade groups, `/api/v1/tags`, `/api/v1/strategies` — is unchanged, as are the
component filename and the `docs/trade-tagging.md` doc filename.

## Scope

**In scope**

- `NAV_ITEMS` label + path, the route, and the layout branch in `frontend/src/App.tsx`
- Page heading, subtitle, and the left-panel heading in `TradeTaggingPage.tsx`
- Every in-app link that targets `/tagging`
- Doc/README/script-comment prose that names the nav item or the URL

**Out of scope (confirmed with the user)**

- Component/file renames — `TradeTaggingPage.tsx`, its default export, and the
  `TradeGroup*`/`Tag*` type exports stay as they are
- `docs/trade-tagging.md` filename and `docs/screenshots/tagging-demo.png` filename
- Backend routers, API paths, DB tables, migrations, commit scopes (`fix(tagging):`)
- **No `/tagging` redirect.** Old bookmarks fall through the catch-all to `/tradebot`.
  Single-operator app; the user accepted the hard break.

## Key decisions

| #    | Decision                                             | Rationale                                                                                                                                                                                                             |
| ---- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| KTD1 | UI + URL only; no code-identifier or doc-file rename | Keeps the diff reviewable and avoids churning the `demoData.ts` type imports and the `docs/_index.md` / `core/trade-group-meta-yaml.md` inbound links. `docs/trade-tagging.md` still accurately titles the subsystem. |
| KTD2 | Hard break on `/tagging`, no `<Navigate>` redirect   | User-directed. One operator, no external consumers of the URL.                                                                                                                                                        |
| KTD3 | Left panel heading becomes **"Strategy List"**       | The page is now "Strategies"; leaving the panel labeled "Strategies" would repeat the word three times (nav → h2 → h3). "Strategy List" keeps the three-column layout oriented.                                       |
| KTD4 | `isTaggingPage` → `isStrategiesPage`                 | Local `App.tsx` variable only — it gates the flex layout branch and would read as stale otherwise. This is the one identifier rename inside the UI-only scope.                                                        |

---

## Implementation units

### U1. Route, nav label, and layout branch

**Files:** `frontend/src/App.tsx`

**Approach:**

1. `NAV_ITEMS` line 29: `{ label: "Tagging", path: "/tagging" }` → `{ label: "Strategies", path: "/strategies" }`. Leave nav order unchanged (between Trades and Watch Lists).
2. Route line 112: `path="/tagging"` → `path="/strategies"`. Element stays `<TradeTaggingPage />`.
3. Lines 69/73: `isTaggingPage` → `isStrategiesPage`, comparing against `"/strategies"`.

The `document.title` effect (lines 61-66) derives from `NAV_ITEMS`, so the tab title
becomes `ngv-trader | Strategies` with no further edit. Nav active-state uses
react-router's `isActive` render prop — no pathname string to update.

**Verification:** `/strategies` renders the workspace with the nav item bold; the tab
reads `ngv-trader | Strategies`; the page still fills the viewport (flex layout branch
fires, no double scrollbar). `/tagging` now lands on `/tradebot`.

### U2. Page copy and panel heading

**Files:** `frontend/src/components/TradeTaggingPage.tsx`

**Approach:**

1. Line ~851 `<h2>`: `Trade Tagging` → `Strategies`.
2. Subtitle (lines ~852-864): drop the now-redundant "Manage strategies and" lead —
   e.g. `Manage strategies and their trade groups. Assign trades from the Trades page.`
   Keep the existing `<a href="/trades">` link untouched.
3. Line ~872 `<h3>`: `Strategies` → `Strategy List` (per KTD3).
4. Line ~480 error copy: `"Failed to load trade tagging workspace."` →
   `"Failed to load strategies workspace."`

Leave the `{/* Column 1: Strategies */}` comment, all `strategies` /
`showArchivedStrategies` / `loadStrategies` state and handlers, and the audit reason
string on line ~783 (`reason=deleted+from+tagging+page`) alone — that string is written
to `trade_group_execution_events` history and changing it would split the audit trail
across two values.

**Verification:** heading reads "Strategies", left panel reads "Strategy List", the
Show archived checkbox and + New button still sit on the panel header row.

### U3. In-app deep links

**Files:** `frontend/src/components/JobsTable.tsx`,
`frontend/src/components/PositionsTable.tsx`,
`frontend/src/components/TradeGroupSearchSelect.tsx`

**Approach:** same one-token substitution in each — `/tagging` → `/strategies`.

- `JobsTable.tsx:84` — `to={\`/tagging?trade_group_id=${String(value)}\`}` (plus the
  line 70-71 comment that says "tagging page").
- `PositionsTable.tsx:945` — `to={\`/tagging?trade_group_id=${group.id}\`}`.
- `TradeGroupSearchSelect.tsx:~289` — `window.open(\`/tagging?${params}\`, "\_blank", ...)`carrying`account_id`+`prefill_group_name`.

Query-param names (`strategy_id`, `trade_group_id`, `account_id`, `prefill_group_name`)
are **not** renamed — `TradeTaggingPage`'s `useSearchParams` deep-link handling and its
`{ replace: true }` URL-sync effect keep working untouched.

**Verification:** from Positions, clicking a trade-group chip opens
`/strategies?trade_group_id=<id>` and the page auto-selects both the group and its
parent strategy (the `fetchGroupStrategyValue` resolution path at lines ~448-470).
From a job row with a `trade_group_id` payload, the same. From
`TradeGroupSearchSelect`, "Create one" opens a new tab prefilled with the group name.

**Test expectation:** none — pure link-target substitution, no test suite covers
routing. `frontend/src/lib/demoData.test.ts` has no `/tagging` reference and is
unaffected.

### U4. Docs, README, and script comments

**Files:** `docs/getting-started.md`, `docs/core/intraday-tws-overlay.md`,
`docs/trade-tagging.md`, `README.md`, `frontend/scripts/screenshot.mjs`, `AGENTS.md`

**Approach:** update prose that names the **nav item or URL**; leave prose that names
the **domain concept** (tagging, tags, tag links) alone.

- `docs/getting-started.md:254` — Pages table row: `| **Tagging** | \`/tagging\` |`→`| **Strategies** | \`/strategies\` |`.
- `docs/core/intraday-tws-overlay.md:116` — "Both the Tagging page (`/tagging`)" →
  "Both the Strategies page (`/strategies`)".
- `docs/trade-tagging.md:298` — "operator manages strategy and trade-group metadata in
  `/tagging`" → `/strategies`. Add one line near the top (~L3) noting the UI surface is
  the **Strategies** page so the doc title and the nav label reconcile. Line 256's
  "### Tagging workspace" heading and line 258's component reference may stay.
- `README.md:27` — section heading `### Trade Tagging` → `### Strategies`. Leave the
  image path `docs/screenshots/tagging-demo.png` on line 32 as-is (KTD1); regenerate
  the image contents in place during verification.
- `frontend/scripts/screenshot.mjs:8` — usage example
  `"/tagging?demo=1&trade_group_id=103"` → `"/strategies?demo=1&trade_group_id=103"`.
- `AGENTS.md:105,124` — the "positions, orders, trades, tagging, pricing, tradebot chat"
  component lists: change to "strategies" so the survey matches the shipped nav.
  Leave `AGENTS.md:120` (`TradeGroup*`/`Tag*` (tagging)) and the `fix(tagging):` commit-scope
  example — those describe models and commit conventions, not the page.

Do **not** touch `docs/plans/*`, `docs/solutions/*`, or `TODO.md` history — dated
artifacts stay as written. `docs/_index.md` needs no edit: no doc file is renamed, and
its line 23 description ("...and tagging UI") can optionally read "...and the Strategies
UI" for accuracy.

**Verification:** `uv run python scripts/doc_check.py` exits 0. No file renames means
`check_internal_links` has nothing new to resolve.

---

## Dependencies

U1 → U2, U3 (route must exist before links point at it, though the edits are
independently safe). U4 has no code dependency and can land in the same commit.

## Risks

- **Bookmark breakage** — accepted per KTD2. Anyone with `/tagging` bookmarked silently
  lands on Tradebot with no explanation. Mitigation if it becomes annoying: add
  `<Route path="/tagging" element={<Navigate to="/strategies" replace />} />` later;
  react-router preserves the query string on `Navigate` with `replace`.
- **Missed link** — a `/tagging` string left in an unreviewed component would 404 into
  the catch-all. Guarded by the grep in Verification below.
- **Doc drift** — the doc file is still named `trade-tagging.md` while the page is
  "Strategies". Accepted (KTD1); the added note in U4 makes the mapping explicit.

## Verification

1. **No stragglers:**
   `grep -rn "/tagging" frontend/src frontend/scripts docs README.md AGENTS.md` returns
   only intentional leftovers (the audit-reason string is `deleted+from+tagging+page`,
   not a path, so it won't match).
2. **Typecheck/lint:** `cd frontend && bun run build` (or the repo's tsc/lint task).
3. **Doc check:** `uv run python scripts/doc_check.py` — expect exit 0.
4. **Demo-mode smoke, no backend needed** — with `task frontend` running:
   - `/strategies?demo=1` renders the three-column workspace, nav item bold, tab title
     `ngv-trader | Strategies`.
   - `/strategies?demo=1&trade_group_id=103` deep-links to that group with its parent
     strategy selected.
   - `/positions?demo=1` → click a trade-group chip → lands on `/strategies?...`.
   - `/tagging?demo=1` → redirects to `/tradebot` (expected hard break).
5. **PR screenshot** (required by AGENTS.md for UI changes):
   ```
   cd frontend
   node scripts/screenshot.mjs "/strategies?demo=1" ../docs/screenshots/tagging-demo.png 1600 900
   ```
   Overwrites the existing file in place, so the README link keeps resolving.

## Definition of done

- Nav, heading, panel heading, tab title, and route all read Strategies / `/strategies`
- Every in-app link targets `/strategies`; no `/tagging` path remains in `frontend/src`
- `doc_check.py` passes; docs and README describe the Strategies page
- `docs/screenshots/tagging-demo.png` regenerated from `/strategies?demo=1`
- Commit: `refactor(ux): rename Tagging page to Strategies`
