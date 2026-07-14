---
title: "feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery"
type: feat
status: active
created: 2026-07-08
---

# feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery

## Summary

In the Trades table, "unsettled" executions sourced from the real-time TWS
(intraday) feed render with **less** contract information than "filled"
executions sourced from FlexQuery/settled TWS:

- A VIX future shows as bare **"VIX"** instead of **"VIX Aug'26"** (no contract
  month).
- The combo/leg relationship is lost: the BAG summary fill is not labeled
  **COMBO** and its futures legs are not labeled **LEG** — every unsettled row
  shows role **"—"**.
- The **Action** column (Open/Close) is blank — unsettled rows show **"—"**
  instead of **Open**/**Close**, even though the settled path derives this from
  the same TWS fill fields.

The data to fix this is available in the same `ib_async` Fill objects the
settled path already consumes; the live-overlay path simply discards it at
ingest and does not derive it at display. This plan restores parity in four
layered fixes:

- **A** — recover the contract month at _display_ time via the existing
  local-symbol inference (no schema change; immediate visible win).
- **B** — capture the authoritative expiry at _ingest_ time behind a new
  `last_trade_date` column (migration).
- **C** — capture an order grouping key + `exec_role` at ingest and port the
  BAG/leg tagging from the settled path so unsettled combos show COMBO/LEG
  (migration).
- **D** — **derive** the open/close indicator (the real-time fill carries no
  position-effect flag) so unsettled rows show the **Action** (Open/Close),
  using the realized-P&L signal we already capture. Best-effort; FlexQuery
  corrects it at settlement.

Fix A is independently shippable and delivers the most visible improvement. B,
C, and D build on A to reach full parity.

**Not achievable from this feed:** the **Expired** action. An option expiration
produces no execution/fill, so it never appears in the real-time TWS fills feed
— it is sourced from FlexQuery only. Unsettled rows will therefore never show
Expired; this is a data-source limitation, not a bug. See Scope Boundaries.

---

## Problem Frame

Two TWS ingestion pipelines exist, and only the intraday one feeds "unsettled":

|         | Settled ("filled")                                                                             | Unsettled ("unsettled")                                       |
| ------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Ingest  | `src/services/trade_sync_tws.py` / `src/services/trade_sync_flexquery.py` → `trade_executions` | `src/services/intraday_sync_tws.py` → `live_executions`       |
| Display | `_contract_display_from_raw()` in `src/api/routers/trades.py`                                  | `_unsettled_live_executions()` in `src/api/routers/trades.py` |

Root causes, confirmed by reading the code:

1. **Month lost at ingest.** `_live_execution_values()`
   (`src/services/intraday_sync_tws.py:284`) never reads
   `contract.lastTradeDateOrContractMonth`, and `LiveExecution`
   (`src/models.py:887`) has no column for it.
2. **Month not recovered at display.** `_unsettled_live_executions()`
   (`src/api/routers/trades.py:843`) calls `contract_display_name(...,
contract_expiry=None, contract_month=None)`. For a `FUT`,
   `contract_display_name` (`src/utils/contract_display.py:94`) builds the label
   purely from expiry/month — both `None` yields the bare symbol. The settled
   path avoids this because `_contract_display_from_raw`
   (`src/api/routers/trades.py:120`) _infers_ the month from `local_symbol`
   (e.g. `VXQ6` → Aug'26) via `infer_contract_month_from_local_symbol` and
   `_parse_local_symbol_contract_month`. The live path skips that fallback even
   though `LiveExecution.local_symbol` is populated.
3. **Combo/leg never computed.** `exec_role` is hardcoded to `"standalone"`
   (`src/api/routers/trades.py:862`); `LiveExecution` has no `exec_role` column
   and the live path does none of the BAG-detection/leg-retagging that
   `trade_sync_tws.py:330-410` performs. It also has **no order/perm-id column**,
   so there is currently no key to group legs to their BAG summary fill.
4. **Action (Open/Close) not derived, and the fill carries no position-effect
   flag.** `_unsettled_live_executions` hardcodes `trade_lifecycle=None`
   (`src/api/routers/trades.py:878`), so the Action column is blank. The settled
   path derives Action via `_trade_lifecycle_from_execution`
   (`src/api/routers/trades.py:224`), which reads `openClose` / `positionEffect`
   from `raw.execution`. **Critical finding:** the real-time `ib_async.Execution`
   object (v2.1.0) has **no `openClose` and no `positionEffect` field** — its
   fields are `execId, time, acctNumber, exchange, side, shares, price, permId,
clientId, orderId, liquidation, cumQty, avgPrice, orderRef, evRule,
evMultiplier, modelCode, lastLiquidity, pendingPriceRevision`. The settled-TWS
   `getattr(execution, "openClose", None)` (`trade_sync_tws.py:71-72`) therefore
   always yields `None`; the Open/Close shown on **filled** rows comes from
   **FlexQuery**'s authoritative `Open/CloseIndicator`, not the TWS sync. IBKR
   does not stamp a fill with cover-vs-add — open/close is a FIFO position-netting
   determination made post-trade. So for real-time rows the indicator must be
   **derived**, not captured (see U4). (`_trade_lifecycle_from_execution` also
   returns "Roll" for `combo_summary`, so once U3 sets `exec_role`, combo
   summaries get a lifecycle for free.)

The frontend (`frontend/src/components/TradesTable.tsx`) already renders
`contract_display`, derives the role badge from `exec_role`, and renders the
Action column from `trade_lifecycle` — it needs no change, only correct values
fed to it.

---

## Scope Boundaries

**In scope**

- Contract-month display parity for unsettled FUT/FOP/OPT rows.
- Authoritative expiry capture on `live_executions`.
- COMBO/LEG role parity for unsettled rows, including capturing an order
  grouping key.
- Action (Open/Close) parity for unsettled rows via the `openClose` /
  `positionEffect` fields on the real-time fill.

**Out of scope / non-goals**

- **Expired action for unsettled rows** — not derivable from the real-time TWS
  fills feed (an expiration produces no fill). It is a FlexQuery-only signal;
  unsettled rows correctly never show Expired. Documented limitation, not a bug.
- Any change to the settled/FlexQuery pipelines or their display path — they are
  the parity _reference_, not a target.
- Frontend changes — the table already renders `contract_display`, the role
  badge, and the Action column correctly from the API contract.
- Realized-P&L, tagging, or dedup behavior of unsettled rows — untouched.

### Deferred to Follow-Up Work

- Backfilling the new columns for `live_executions` rows already in the DB. Live
  rows are short-lived (purged as they settle, per `_purge_settled`), so the
  next intraday sync repopulates them; a backfill is unnecessary. Note only.
- Persisting a synthesized BAG "combo summary" row when TWS delivers only legs
  (no BAG fill). The settled FlexQuery path synthesizes one
  (`_synthesize_combo_summary`); the live path will rely on TWS actually
  delivering the BAG fill (as it does in the reported case). Revisit only if
  live combos appear without a BAG fill.

---

## Key Technical Decisions

1. **Fix A reuses `_contract_display_from_raw` rather than duplicating inference.**
   In `_unsettled_live_executions`, synthesize a TWS-shaped
   `raw = {"contract": {...}}` from the `LiveExecution` fields and route it
   through the existing `_contract_display_from_raw`. This inherits the full
   fallback chain (explicit expiry → local-symbol month inference → OCC option
   parsing) for free and keeps a single display code path. Rationale: the
   inference logic is non-trivial and already battle-tested for settled rows;
   duplicating it invites drift.

2. **Fix B stores the raw IBKR expiry string, not a parsed date.** Add
   `last_trade_date: str | None` mirroring IBKR's
   `lastTradeDateOrContractMonth` (either `YYYYMMDD` or `YYYYMM`). The display
   layer already normalizes both shapes (`_contract_display_from_raw:130-133`),
   so storing the raw string keeps ingest dumb and display authoritative.

3. **Fix C needs an order grouping key.** BAG and leg fills arrive as separate
   `Fill`s; the settled path groups them by trade (perm/order id). `LiveExecution`
   stores neither. Add `perm_id` (and/or `ib_order_id`) so legs can be grouped to
   their BAG summary within a sync batch. Group key preference: `permId` (stable
   across the order lifecycle); fall back to `orderId` when `permId` is absent.

4. **Tagging is computed per sync batch, then persisted.** Unlike the settled
   path (which re-tags via DB queries over a trade's executions), the live path
   computes `exec_role` in-memory over the current `ib.fills()` batch grouped by
   order key, then writes it. This keeps the intraday sync self-contained and
   idempotent on `ib_exec_id`.

5. **Ordering: A → (B, C, D).** A ships alone and is display-only/reversible. B
   and C each add nullable column(s); D needs no migration (display-only
   derivation). All are safe to land together or separately.

6. **Fix D derives open/close from realized P&L — no new column, no fabricated
   flag.** The real-time `Execution` carries no `positionEffect`, so we infer it:
   IBKR reports a non-zero `realizedPNL` only when a fill _reduces_ a position (a
   FIFO close). Rule: `realized_pnl` non-zero → **Close**; zero/absent → **Open**.
   Combined with `side`, this expresses cover-vs-add (BUY+Close = cover,
   BUY+Open = add). `realized_pnl` is already stored on `LiveExecution`, so no
   migration is needed for D. This is a best-effort proxy: FlexQuery's
   authoritative `Open/CloseIndicator` supersedes it once the row settles, and a
   rare exact-breakeven scratch close would misclassify as Open. `combo_summary`
   rows still resolve to "Roll" via `_trade_lifecycle_from_execution` once U3
   lands. **Alternative considered:** position-netting against
   `live_positions` — more precise but needs the pre-fill (start-of-day)
   position and sequential replay; deferred unless the realized-P&L proxy proves
   insufficient.

---

## Implementation Units

### U1. Fix A — recover contract month at display time

**Goal:** Unsettled FUT/FOP/OPT rows show the contract month (e.g. "VIX Aug'26")
using existing local-symbol inference, with no schema change.

**Requirements:** Restores the primary reported gap (missing contract months).

**Dependencies:** none.

**Files:**

- `src/api/routers/trades.py` — modify `_unsettled_live_executions` (~line 843).
- `tests/` — add/extend the test module covering `_unsettled_live_executions`
  (locate existing trades-router tests; create
  `tests/api/routers/test_trades_unsettled.py` if none covers this path).

**Approach:** Replace the direct `contract_display_name(..., contract_expiry=None,
contract_month=None)` call with construction of a synthetic
`raw = {"contract": {...}}` from the `LiveExecution` (`symbol`, `sec_type`,
`local_symbol`, `right`, `strike`, `con_id`, `multiplier`) and pass it through
`_contract_display_from_raw`. Fall back to the current bare
`contract_display_name` result only if `_contract_display_from_raw` returns
`None`. Assign the result to both `contract_display` and
`trade_contract_display_name`.

**Patterns to follow:** `_contract_display_from_raw` and its caller for settled
rows (`src/api/routers/trades.py:120`, ~779); the raw-contract shape synthesized
in `src/services/trade_sync_flexquery.py:_row_raw` (line 196).

**Test scenarios:**

- VIX future live row with `local_symbol="VXQ6"`, `sec_type="FUT"`,
  no expiry → display is `"VIX Aug'26"` (month inferred from local symbol).
- VIX BAG live row (`sec_type="BAG"`, `local_symbol` present) → display uses the
  BAG branch (local symbol or bare `VIX`), unchanged by inference.
- Live row with unparseable/empty `local_symbol` and `sec_type="FUT"` → falls
  back to bare `"VIX"` (no crash, no `None`).
- FOP/OPT live row with OCC-style `local_symbol` → strike/right/expiry render as
  for settled rows.
- Regression: settled rows in the same response are unchanged.

**Verification:** In the Trades table, unsettled VIX futures show the month
matching the corresponding settled rows for the same expiry.

---

### U2. Fix B — capture authoritative expiry at ingest

**Goal:** Persist IBKR's `lastTradeDateOrContractMonth` on `live_executions` and
prefer it over inference at display.

**Requirements:** Makes the month authoritative rather than inferred; future-proofs
symbols where local-symbol inference is unreliable.

**Dependencies:** U1 (display path already routes through
`_contract_display_from_raw`).

**Files:**

- `src/models.py` — add `last_trade_date: Mapped[str | None]` to `LiveExecution`
  (~line 912).
- `alembic/versions/<new>.py` — migration adding nullable `last_trade_date` to
  `live_executions`.
- `src/services/intraday_sync_tws.py` — `_live_execution_values` (line 284) reads
  `contract.lastTradeDateOrContractMonth`.
- `src/api/routers/trades.py` — include `last_trade_date` as
  `lastTradeDateOrContractMonth` in the synthetic `raw` built in U1.
- `tests/` — extend U1 test module + intraday-sync test.

**Approach:** Add the nullable column via Alembic (per project convention — DB
changes go through migrations, see prior PR #60). Capture the field in
`_live_execution_values`. In the U1 synthetic `raw`, populate
`contract["lastTradeDateOrContractMonth"] = le.last_trade_date`, which
`_contract_display_from_raw` already prefers over inference.

**Patterns to follow:** `alembic/versions/20260620185103_add_intraday_overlay_tables.py`
for column/style; `_row_raw` in `trade_sync_flexquery.py` for the raw contract
shape; `_fill_to_raw` gap noted in `trade_sync_tws.py` (also omits this field).

**Execution note:** Migration is additive and nullable — no backfill required
(live rows are short-lived and repopulated each sync).

**Test scenarios:**

- `_live_execution_values` maps a fill whose
  `contract.lastTradeDateOrContractMonth="20260819"` to
  `last_trade_date="20260819"`.
- Fill missing the attribute → `last_trade_date=None` (no crash).
- Display: live row with `last_trade_date="20260819"` and a _different_
  `local_symbol` → month comes from `last_trade_date` (Aug'26), proving stored
  expiry wins over inference.
- Display: live row with `last_trade_date=None` but valid `local_symbol` → still
  infers month (U1 fallback intact).
- Migration upgrade/downgrade runs cleanly against the schema.

**Verification:** New live fills persist `last_trade_date`; the Trades table
month matches the settled row for the same contract even when local-symbol
inference would differ.

---

### U3. Fix C — capture order key + exec_role and tag combos at ingest

**Goal:** Unsettled combo fills show COMBO (BAG summary) and LEG (constituent
futures) roles matching the settled path.

**Requirements:** Restores the reported combo-vs-leg gap for unsettled rows.

**Dependencies:** U1 (display), U2 (migration precedent). Can share U2's migration
or add its own.

**Files:**

- `src/models.py` — add `exec_role: Mapped[str]` (default `"standalone"`) and an
  order grouping key (`perm_id: Mapped[int | None]`, and/or
  `ib_order_id: Mapped[int | None]`) to `LiveExecution`.
- `alembic/versions/<new>.py` — migration adding the columns (nullable /
  defaulted).
- `src/services/intraday_sync_tws.py` — `_live_execution_values` captures the
  order key; `_write_fills` (line 306) computes `exec_role` per batch grouped by
  order key before upserting.
- `src/api/routers/trades.py` — `_unsettled_live_executions` emits `le.exec_role`
  instead of the hardcoded `"standalone"` (line 862); set `sec_type`/display via
  U1 path (BAG already handled).
- `tests/` — intraday-sync tagging test + serializer role test.

**Approach:** Capture `execution.permId` / `execution.orderId` (and read the fill
contract's `secType`) in `_live_execution_values`. In `_write_fills`, before
upserting, group the batch's fills by order key; within each group, tag
`secType=="BAG"` fills as `combo_summary` and their non-BAG siblings as `leg`;
leave ungrouped/solo fills as `standalone`. Persist `exec_role`. In the
serializer, pass `le.exec_role` through. The frontend `execRoleBadge` then
renders COMBO/LEG automatically.

**Patterns to follow:** BAG detection and leg re-tagging in
`src/services/trade_sync_tws.py:330-410`; `_combo_groups` grouping semantics in
`src/services/trade_sync_flexquery.py:163` (requires ≥2 distinct conids to
qualify as a real multi-leg combo — mirror this guard to avoid mislabeling a
lone BAG or a single-leg order).

**Test scenarios:**

- Batch with one `BAG` fill + two `FUT` fills sharing a `permId` → BAG tagged
  `combo_summary`, both FUT tagged `leg`.
- Batch with a single standalone `FUT` fill (no BAG, unique order) → stays
  `standalone`.
- Two independent orders in one batch → legs tag only within their own order
  group (no cross-order leakage).
- Fills missing `permId` but sharing `orderId` → grouped by fallback key.
- Guard: a BAG order with only one distinct conid does not mislabel (mirror
  `_combo_groups` ≥2-conid rule).
- Serializer: a `combo_summary` live row → response `exec_role="combo_summary"`
  → frontend renders COMBO; a `leg` row → LEG.
- Idempotency: re-running the sync on the same fills yields identical
  `exec_role` (upsert on `ib_exec_id`).

**Verification:** In the Trades table, the reported unsettled VIX combo shows the
BAG row as COMBO and the two futures as LEG, matching the settled combos above
it.

---

### U4. Fix D — derive Open/Close (Action) from realized P&L

**Goal:** Unsettled rows show the **Action** (Open/Close) — and thus cover-vs-add
when combined with Side — derived from the realized-P&L signal already captured,
since the real-time fill carries no `positionEffect`.

**Requirements:** Restores the reported Action-column gap for unsettled rows,
within the limits of what the real-time feed supports.

**Dependencies:** U1 (display path). No migration required (`realized_pnl`
already exists on `LiveExecution`). Synergizes with U3 (combo_summary → "Roll").

**Files:**

- `src/api/routers/trades.py` — add a small helper (e.g.
  `_lifecycle_from_live_execution(le)`) and set `trade_lifecycle=...` in
  `_unsettled_live_executions` instead of `None` (line 878).
- `tests/` — serializer lifecycle test over live rows.

**Approach:** Derive the indicator with the rule: `exec_role == "combo_summary"`
→ "Roll" (mirror `_trade_lifecycle_from_execution`); else a non-zero, non-null
`le.realized_pnl` → "Close"; else "Open". Feed nothing through the raw-based
`_trade_lifecycle_from_execution` (the live row has no `openClose` to read) —
this is a live-specific derivation. Document inline that this is a best-effort
proxy corrected by FlexQuery at settlement.

**Patterns to follow:** `_trade_lifecycle_from_execution`
(`src/api/routers/trades.py:224`) for the "Roll" rule and the Open/Close display
vocabulary; the realized-P&L capture in `_fill_realized_pnl`
(`src/services/intraday_sync_tws.py:111`).

**Test scenarios:**

- Live BUY row with `realized_pnl=275.26` → `trade_lifecycle="Close"` (buy to
  cover a short) — matches the `CL 77 CALL BOT` case in the report.
- Live BUY row with `realized_pnl=0.0` → `trade_lifecycle="Open"` (buy to add) —
  matches the `GLD 383 CALL BOT` case.
- Live SELL row with `realized_pnl=0.0` → `"Open"` (sell to open a short).
- Live SELL row with non-zero `realized_pnl` → `"Close"` (sell to exit a long).
- `realized_pnl=None` → `"Open"` (no realized P&L reported → treated as open).
- `combo_summary` row (from U3) → `"Roll"` regardless of realized P&L.
- Regression: a standalone unsettled row's other fields (display, role)
  unaffected.

**Execution note:** Guard the zero check against float noise if realized P&L can
arrive as a tiny non-zero residual; treat `abs(realized_pnl) < epsilon` as zero
only if observed in practice — otherwise exact `!= 0` is fine.

**Verification:** Unsettled rows show Open/Close consistent with the realized-P&L
column (rows with realized P&L read as Close/cover; flat rows as Open/add), and
the value flips to the FlexQuery-authoritative indicator once the row settles.

---

## System-Wide Impact

- **DB:** nullable/defaulted columns added to `live_executions`
  (`last_trade_date`, `exec_role`, an order key). D adds no column — it derives
  Action from the existing `realized_pnl`. Additive; no backfill.
- **Intraday sync worker** (`intraday.sync.tws`, `src/workers/jobs.py:638`):
  writes the new fields each run. No schedule/behavior change.
- **API `GET /trade-executions`:** unsettled items gain accurate
  `contract_display`, `exec_role`, and `trade_lifecycle`; response schema
  (`TradeExecutionListItem`) is unchanged (fields already exist).
- **Frontend:** none — consumes existing fields.

---

## Risks & Mitigations

- **Local-symbol inference wrong for some symbols (A):** mitigated by B making
  the stored expiry authoritative; A's inference is only a fallback.
- **Combo grouping key absent/instmislabeled (C):** mirror the settled path's
  ≥2-distinct-conid guard and prefer `permId`; solo/ungrouped fills default to
  `standalone` (current behavior), so worst case is no regression.
- **Migration drift noise:** the intraday-overlay migration noted unrelated
  autogenerate churn; hand-write the migration to add only the new columns (as
  that migration did).

---

## Test / Verification Strategy

- Unit tests per unit as enumerated above (intraday-sync value mapping + batch
  tagging; serializer display + role).
- Manual: run the intraday sync against a session that has today's VIX combo
  fills; confirm the Trades table unsettled rows show month + COMBO/LEG matching
  the settled reference rows.
- Repo checks: `uv run python scripts/check.py` (or the repo's configured
  `ruff` + checks) as used by the intraday-overlay work.
