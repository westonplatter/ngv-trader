---
title: Fix Stale Descriptions in docs/design - Plan
type: docs
date: 2026-10-10
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-plan-bootstrap
execution: code
---

# Fix Stale Descriptions in docs/design - Plan

## Goal Capsule

- **Objective:** A reader of `docs/design/` learns how the product works today. No passage describes a behavior the code has since changed.
- **Means:** Rewrite each passage a code-grounded staleness review confirmed as wrong, citing the code that now governs it (KTD1).
- **Authority:** The code is the source of truth. Where a doc and the code disagree, the doc changes. Where the executor cannot confirm a claim from the code, the executor says so in the doc rather than guessing.
- **Stop conditions:** Stop and report if a correction would require describing an account by alias or by real activity, or if a cited code location no longer matches the finding.
- **Execution profile:** Documentation edits only. No code, schema, or data changes.
- **Finisher:** The executing agent lands the edits and runs the checks. The maintainer reviews and merges.

## Product Contract

### Summary

Rewrite the confirmed-stale passages in seven `docs/design/` docs so they match the code, and remove the account identifiers that one of them should never have carried.

### Problem Frame

The design docs were written as features shipped and were not revisited when later work changed behavior. A code-grounded review on 2026-10-10 compared each of the seventeen docs' claims to the code. Ten were accurate. Seven carry passages that now mislead: the semantic-layer docs describe a trade-group attribution model the P&L service replaced, the pricing doc describes a leg-selection order the page no longer uses, the overlay and SSE docs describe loader, action, and event cadence rules that changed, and the sync and display-name docs state aggregation and formatting rules the code no longer follows. The review also found concrete account aliases and real P&L figures in a committed doc, which the repo's data rules forbid.

### Requirements

**Accuracy**

- R1. Every passage listed under Implementation Units is rewritten to describe current behavior, with the governing code path named in the doc the way surrounding text already names code.
- R2. A rewrite adds no claim the executor has not confirmed by reading the cited code.
- R3. Where the SQL metric and the MCP tool now differ, the doc states the difference explicitly instead of asserting they share a rule.

**Data policy**

- R4. `docs/design/semantic-data-model.md` carries no account alias and no trade group tied to real P&L figures. Examples use the placeholder conventions in `docs/ibkr-sample-data.md` under "Account References in Committed Content".

**Hygiene**

- R5. `uv run python scripts/docs_check.py` passes after the edits.
- R6. Each doc's remaining content is left as written. This plan fixes the flagged passages; it is not a rewrite.

### Scope Boundaries

- The ten docs the review found accurate are untouched: `tradebot-chatbot.md`, `option-metrics-overlay.md`, `security-data.md`, `contract-ref-setup.md`, `trade-tagging.md`, `trade-group-meta-yaml.md`, `user-preferences-privacy-mode.md`, `ux-actions.md`, `workers.md`, and the core of both semantic docs.
- Style, link, and index work is out of scope. Links were repaired separately on 2026-10-10.
- The `ngv_analyst` GRANT list in `semantic-queries.md` is corrected as text only. Changing the real role's grants is a migration and is not planned here.

#### Deferred to Follow-Up Work

- Code gap, not a doc fix: the docstring on the FlexQuery trade-matching function in `src/services/trade_sync_flexquery.py` still describes a `trade_date` check the function does not perform and names an unused parameter. The doc is right and the docstring is wrong. File it as a separate code change.
- Incomplete lists that are not wrong: `user-preferences-privacy-mode.md` omits `StrategyPnlTable` from its affected-components list, and `trade-tagging.md`'s workspace feature list omits strategy archive/unarchive and the meta YAML editor.
- Wording only: `workers.md` says the positions sync default window is "one day"; the code passes a zero-day span ending on the prior business day.

### Open Questions

- Resolve during U6: `api-ux-sse.md` says a connection status badge renders in component headers. The reviewer found no JSX that renders the SSE status; every consumer uses it only to refetch on reconnect. The executor confirms by searching `frontend/src` for a rendered status element. If none exists, remove the badge sentence; if one exists in a shared layout, leave it and name the component.

## Planning Contract

### Key Technical Decisions

- KTD1. **Correct passages in place; do not add a changelog or "previously" note.** The docs are current-state docs. A superseded description is removed, not annotated. Version control holds the history.
- KTD2. **Name the governing code by path and symbol, never by line number.** Surrounding docs already follow this (`docs/doc-review.md`, Conventions). Line numbers in this plan's evidence are for the executor to locate the code and are not copied into the docs.
- KTD3. **Fix the data-policy violation as its own unit.** It is a different kind of change from a staleness fix and should be reviewable on its own.

### Evidence

Code the review used to confirm each finding. Symbols are stable; line numbers are approximate.

| Finding                                                              | Code                                                                                                                                                                                                                                                       |
| -------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Tool passes magnifiers and option metrics into the overlay           | `src/services/trade_group_pnl.py`, `load_overlay_context` reads `ContractRef.price_magnifier` and `LatestOptionMetrics`; the `merge_positions` call near line 653 passes both. Same call in `src/api/routers/trade_groups.py` near line 1370.              |
| Tool widens attribution with tagged unsettled live fills             | `src/services/trade_group_pnl.py`, `_tagged_live_pairs` and its use near line 649, with the comment that the service and detail endpoint scope the overlay identically.                                                                                    |
| Tool apportions shared positions pro rata                            | `src/services/trade_group_pnl.py`, `apportion_to_group` (near line 146) and the service docstring near line 624. Called near line 655 and in `trade_groups.py` near line 1373.                                                                             |
| SQL metric still many-to-many                                        | `alembic/versions/20260704214134_position_trade_group_bridge_view.py`, view docstring.                                                                                                                                                                     |
| Tool reads two tables the documented role cannot                     | `src/services/trade_group_pnl.py` reads `latest_option_metrics` (near line 265) and `trade_group_live_executions` via `_tagged_live_pairs` (near line 345).                                                                                                |
| Pricing leg order is Expiry then Strike                              | `frontend/src/components/PricingPage.tsx`, comments "Expiry (was DTE — now comes before Strike)" near line 1193 and "Strike (filtered by selected expiry)" near line 1250; placeholder "Pick expiry first" near line 1270.                                 |
| Expected-P&L request body                                            | `frontend/src/components/PricingPage.tsx`, request construction near lines 586 to 610.                                                                                                                                                                     |
| Positions endpoint does not use the shared overlay loader            | `src/api/routers/positions.py`, six inline selects near lines 344 to 354; `load_overlay_context` is not referenced in that file.                                                                                                                           |
| Live combo summary action is rolled up from legs                     | `src/api/routers/trades.py`, `_combo_lifecycle` near line 234 (Open if all legs Open, Close if all Close, Roll if mixed); returned near line 918.                                                                                                          |
| Worker heartbeat notifies only on change or after 30 s               | `src/services/worker_heartbeat.py`, `_FORCE_NOTIFY_AFTER_SECONDS` near line 29 and the `status_changed or stale` guard near line 105.                                                                                                                      |
| `trades.sync.tws` has no registered handler                          | `src/workers/jobs.py`, dispatch map near lines 886 to 909 and its comment that the TWS sync entries are not registered while FlexQuery is the active path.                                                                                                 |
| Non-combo parent totals sum all canonical fills                      | `src/services/sync_common.py`, aggregation loop near lines 229 to 238 with no `exec_role` filter.                                                                                                                                                          |
| "Expired" is a trade status from Flex notes, not an Action           | `src/services/sync_common.py`, `_execution_outcome` and `_derive_trade_status` near lines 33 to 74 (notes code `Ep`); `src/api/routers/trades.py`, `_OPEN_CLOSE_DISPLAY` near line 53 maps only Open and Close.                                            |
| BAG display skips an all-digit localSymbol                           | `src/utils/contract_display.py`, `if local and not local.isdigit()` near line 93.                                                                                                                                                                          |
| Month inference returns None; expiry fallback lives in the formatter | `src/services/cl_contracts.py`, `infer_contract_month_from_local_symbol` near line 185; `src/utils/contract_display.py`, `_format_expiry_month_year` near line 10.                                                                                         |
| Trade-level display names now receive a ContractRef                  | `src/api/routers/trades.py`, `_contract_display_from_raw(raw, contract_ref)` in the list route near line 546 and detail route near line 638; `_trade_contract_display_name` near line 203 and the trade-executions grouping near line 796 still pass None. |

## Implementation Units

### U1. Correct trade_group_pnl inputs, attribution, and grants in semantic-queries.md

- **Goal:** Section 8 and section 9 of `docs/design/semantic-queries.md` describe how the MCP `trade_group_pnl` tool and the API compute group P&L today.
- **Requirements:** R1, R2, R3
- **Dependencies:** none
- **Files:** `docs/design/semantic-queries.md`
- **Approach:**
  1. In section 9, remove the passage that says the tool and the API inputs "can diverge in two ways" (magnifiers and option metrics not passed; live-fill pairs not widened). Replace it with one statement that both call paths load the same overlay context and scope it identically, naming `load_overlay_context` and `_tagged_live_pairs`.
  2. In section 9, replace the attribution rule "a position is attributed to a group when any of the group's executions touched its (account_id, con_id)" with the pro-rata rule: the group holds the part of each position its own tagged fills opened, so a contract split across groups is counted once. Name `apportion_to_group`.
  3. In section 9's `settled_unrealized_pnl` note, keep the "not additive across groups" warning for the SQL metric. Remove "same attribution rule as the tool below" and state that the SQL metric and the tool attribute differently.
  4. In section 8, add `latest_option_metrics` and `trade_group_live_executions` to the `ngv_analyst` GRANT list.
- **Patterns to follow:** The existing section 9 prose, which names functions in backticks and keeps one claim per paragraph.
- **Test scenarios:** Test expectation: none -- documentation only. Verification is a read against the cited code.
- **Verification:** Each rewritten sentence can be traced to a symbol in the Evidence table. `uv run python scripts/docs_check.py` passes.

### U2. Correct the attribution caveat in semantic-data-model.md

- **Goal:** Section 5 of `docs/design/semantic-data-model.md` and the section 1 row for `trade_group_pnl` no longer say the tool counts a shared position in every group.
- **Requirements:** R1, R2, R3
- **Dependencies:** U1, so the two docs state the same rule in the same words
- **Files:** `docs/design/semantic-data-model.md`
- **Approach:**
  1. Split the caveat marked "(both)". Keep the double-counting warning for `settled_unrealized_pnl` through `query_metric`.
  2. State that `trade_group_pnl` apportions a shared position by the group's own fills and counts it once, and point to the fuller explanation in `semantic-queries.md`.
- **Patterns to follow:** The doc's existing cross-references to `semantic-queries.md`.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** The doc makes no claim about the tool's attribution that U1's text contradicts. `uv run python scripts/docs_check.py` passes.

### U3. Remove account aliases and real P&L figures from semantic-data-model.md

- **Goal:** `docs/design/semantic-data-model.md` complies with the repo's committed-content rules.
- **Requirements:** R4, R6
- **Dependencies:** none
- **Files:** `docs/design/semantic-data-model.md`
- **Approach:**
  1. In section 4, replace each concrete account alias with a placeholder such as `<ACCOUNT>` or the anonymized account ids from `docs/ibkr-sample-data.md`. Keep the column name `accounts.alias` where the text is about the column.
  2. In section 6, replace the named trade group and its real P&L figures with a placeholder group name and round, obviously illustrative numbers. Keep symbols, sec types, and exchanges real.
  3. Keep the shape of every worked example. The point of each example must survive the substitution.
- **Patterns to follow:** `docs/ibkr-sample-data.md`, "Account References in Committed Content", and the placeholder style in `docs/plans/2026-07-14-001-fix-missing-opening-execution-plan.md`.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** A read of sections 4 and 6 finds no alias and no figure that could be matched to a real account. `uv run python scripts/ibkr_sensitive_data_check.py --paths docs/design/semantic-data-model.md` passes. Note that this scanner does not detect aliases, so the read is the real check.

### U4. Correct the leg cascade and request body in ux-pricing.md

- **Goal:** `docs/design/ux-pricing.md` describes the leg-row flow the Pricing page implements.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:** `docs/design/ux-pricing.md`
- **Approach:**
  1. In "User Flow" and "Left-to-right cascade", change the Call/Put order to Type, then Expiry select, then Strike combobox filtered by the chosen expiry. State that the Strike control shows "Pick expiry first" until an expiry is chosen. Remove the DTE dropdown.
  2. In "Auto-populated fields", remove "via DTE dropdown or auto-select if only one DTE". Describe population as happening when a strike is selected.
  3. In "Pricing Calculation", either list the full request body the page sends (per-leg `ivend`, `rate`, `underlying`; top-level `days_into_future`) or state that the listed fields are a subset and point to the request construction in `PricingPage.tsx`. Pick the first unless the body is likely to keep changing.
- **Patterns to follow:** The doc's existing numbered cascade list.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** Each step in the rewritten cascade matches a control in `PricingPage.tsx` in the same order. `uv run python scripts/docs_check.py` passes.

### U5. Correct loader, merge inputs, and combo action in intraday-tws-overlay.md

- **Goal:** `docs/design/intraday-tws-overlay.md` describes which consumers share the overlay loader, what the merge receives, and how a live combo summary gets its action.
- **Requirements:** R1, R2
- **Dependencies:** U1, so the merge-input wording matches the semantic doc
- **Files:** `docs/design/intraday-tws-overlay.md`
- **Approach:**
  1. Replace "Every consumer loads its rows through `load_overlay_context()`" with the accurate split: trade-group P&L callers use the loader; `GET /positions` runs its own inline selects and merge. The doc already says the latter further down, so make the two passages agree.
  2. Remove the sentence saying `trade_group_pnl` calls the merge with magnifiers and metrics defaulted to None. State that both call sites pass them from the loaded context.
  3. In the unsettled-fills action rule, replace "combo_summary → Roll" with the roll-up rule in `_combo_lifecycle`: Open when every leg is Open, Close when every leg is Close, Roll only when mixed.
- **Patterns to follow:** The doc's existing per-rule bullets that name the function in backticks.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** The doc no longer contradicts itself about the positions endpoint. `uv run python scripts/docs_check.py` passes.

### U6. Correct event cadence and the dead trades.sync.tws path in api-ux-sse.md

- **Goal:** `docs/design/api-ux-sse.md` states when `worker.heartbeat` and `trades.changed` actually fire.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:** `docs/design/api-ux-sse.md`
- **Approach:**
  1. In the event reference row and the publisher note for `worker.heartbeat`, replace "every poll cycle" and "after each heartbeat upsert" with: every poll still upserts, but the SSE notify fires only on a status transition or when 30 seconds have passed since the last notify.
  2. In the `trades.changed` row, drop `trades.sync.tws` as a trigger, or mark it as unregistered while FlexQuery is the active path. Only the FlexQuery fetch_report job fires the hint today.
  3. Resolve the Open Question about the connection status badge and edit or keep the sentence accordingly.
- **Patterns to follow:** The existing event reference table.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** Each trigger named in the event table maps to a notify call in the cited publisher. `uv run python scripts/docs_check.py` passes.

### U7. Correct aggregation wording and the Expired source in trades-and-executions-sync.md

- **Goal:** `docs/design/trades-and-executions-sync.md` states how parent trade totals are aggregated and where the expired outcome comes from.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:** `docs/design/trades-and-executions-sync.md`
- **Approach:**
  1. In the aggregation passage, replace "otherwise from all canonical non-leg fills" with: when a combo summary exists, parent totals come from it; otherwise they sum every canonical fill. Legs are excluded only indirectly, through the combo-summary branch.
  2. Replace "the only source of the Expired action" with: Open/CloseIndicator drives the Open and Close actions; the expired outcome is a trade status derived from the Flex `notes` code `Ep`, and no Expired action value exists.
- **Patterns to follow:** The doc's existing data-flow prose, which names the helper and the column together.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** Each rewritten sentence traces to `sync_common.py` or `trades.py` symbols in the Evidence table. `uv run python scripts/docs_check.py` passes.

### U8. Correct the BAG rule, inference fallback, and Gap section in contract-display-names.md

- **Goal:** `docs/design/contract-display-names.md` states the display rules the helpers implement and the gap that actually remains.
- **Requirements:** R1, R2
- **Dependencies:** none
- **Files:** `docs/design/contract-display-names.md`
- **Approach:**
  1. In both places the BAG rule appears, change "localSymbol if present, else symbol" to: localSymbol when present and not all digits, else symbol. Say why: TWS reports a placeholder combo conId as the localSymbol.
  2. In the futures month inference passage, state that the inference helper returns None when the local symbol pattern does not match or the sec type is not FUT, and that the `contract_expiry` fallback happens in the display formatter.
  3. Narrow the "Gap: Trade-Level Display Names" section. The list and detail routes now pass a ContractRef. The remaining gap is the fallback helper and the per-trade grouping in the trade-executions route, which still pass None.
- **Patterns to follow:** The doc's rule-per-sec-type list.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** The documented BAG rule matches the guard in `contract_display.py`, and the Gap section names only call sites that still pass None. `uv run python scripts/docs_check.py` passes.

### U9. Make the new-secret guidance in secrets-using-1password.md consistent

- **Goal:** `docs/design/secrets-using-1password.md` gives one instruction for reading a new secret in code.
- **Requirements:** R1, R6
- **Dependencies:** none
- **Files:** `docs/design/secrets-using-1password.md`
- **Approach:**
  1. In "Adding new secrets", replace the step that says to read the value with raw `os.environ.get` with the repo pattern the doc's later section already describes: non-DB secrets go through the helpers in `src/utils/env_vars.py` so an `op://` value self-resolves; only the plain `DB_*` vars are read raw.
- **Patterns to follow:** The doc's own "Which vars need `op run`" section.
- **Test scenarios:** Test expectation: none -- documentation only.
- **Verification:** The doc's two statements about how code reads a secret agree. `uv run python scripts/docs_check.py` passes.

## Verification Contract

| Check                                   | Command                                                                  | Applies to                                                |
| --------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------- |
| Doc links, scripts, tasks, spec banners | `uv run python scripts/docs_check.py`                                    | all units                                                 |
| IBKR identifier scan                    | `uv run python scripts/ibkr_sensitive_data_check.py --paths docs/design` | U3, and any unit that adds an example                     |
| Index regeneration                      | `uv run python scripts/docs_index.py`                                    | only if a doc's front matter changes; none is expected to |
| Code trace                              | Read the symbol named in each rewritten sentence                         | U1, U2, U4, U5, U6, U7, U8                                |

## Definition of Done

- Every unit's flagged passages are rewritten and no passage still states the superseded behavior.
- `docs/design/semantic-data-model.md` contains no account alias and no real P&L figure.
- `scripts/docs_check.py` passes and the staged diff passes the IBKR scan.
- No doc outside the eight files named in the units is changed.
- The Open Question about the SSE status badge is resolved in the doc, one way or the other.
