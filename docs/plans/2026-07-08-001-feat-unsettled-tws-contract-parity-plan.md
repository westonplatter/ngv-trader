---
title: "feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery"
type: feat
status: active
created: 2026-07-08
---

# feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery

Unsettled executions from the real-time TWS (intraday) feed rendered with less
information than settled FlexQuery rows. Four layered fixes; **A and C have
shipped**, B and D remain.

| Fix   | Gap                                 | Status                             |
| ----- | ----------------------------------- | ---------------------------------- |
| **A** | contract month/expiry missing       | **shipped** 2026-07-28 (`b28e48c`) |
| **B** | expiry not authoritative (inferred) | open — see U2 below                |
| **C** | combo/leg relationship lost         | **shipped** 2026-07-28 (`1522017`) |
| **D** | Action (Open/Close) blank           | open — see U4 below                |

Shipped behavior now lives in the subsystem docs, not here:
[core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md) (combo roles,
order key, unit tagging) and
[trades-and-executions-sync.md](../trades-and-executions-sync.md) (shared
`exec_role` vocabulary).

**Also unblocked:** C's order key was the hard dependency of the leg-anchored
purge in the bag-summary live-reconciliation work, which can now proceed with
Option 1 rather than the timestamp-heuristic Option 2.

**Not achievable from this feed:** the **Expired** action. An option expiration
produces no execution/fill, so it never appears in the real-time TWS fills feed —
it is sourced from FlexQuery only. Unsettled rows will therefore never show
Expired; a data-source limitation, not a bug.

---

## Remaining work

### U2. Fix B — capture authoritative expiry at ingest

**Goal:** Persist IBKR's `lastTradeDateOrContractMonth` on `live_executions` and
prefer it over inference at display.

**Why it still matters after A.** A recovers the expiry from `local_symbol`,
which is exact for OCC-style equity options (`SPCX  261218P00100000` → Dec18'26)
but only month-precise for futures options, whose local symbol carries no day —
`MCL Jul'26 82.5 CALL` where the settled row would read a specific day. B closes
that residual and future-proofs symbols where inference is unreliable.

**Dependencies:** none remaining — A's display path already prefers a stored
expiry over inference, so this is a drop-in.

**Files:**

- `src/models.py` — add `last_trade_date: Mapped[str | None]` to `LiveExecution`.
- `alembic/versions/<new>.py` — migration adding the nullable column.
- `src/services/intraday_sync_tws.py` — `_live_execution_values` reads
  `contract.lastTradeDateOrContractMonth`.
- `src/api/routers/trades.py` — add `lastTradeDateOrContractMonth` to the
  synthetic `raw` built in `_live_contract_display`.

**Approach:** Store the raw IBKR string (either `YYYYMMDD` or `YYYYMM`), not a
parsed date — the display layer already normalizes both shapes
(`_contract_display_from_raw`), so ingest stays dumb and display authoritative.

**Execution note:** Additive and nullable, no backfill — live rows are
short-lived (purged by `_purge_settled` as they settle) so the next intraday sync
repopulates them. Existing rows keep rendering via A's inference meanwhile.

**Test scenarios:**

- `_live_execution_values` maps a fill with
  `contract.lastTradeDateOrContractMonth="20260819"` to
  `last_trade_date="20260819"`.
- Fill missing the attribute → `None`, no crash.
- Display: row with `last_trade_date` set and a _different_ `local_symbol` →
  month comes from the stored expiry, proving it wins over inference.
- Display: `last_trade_date=None` but valid `local_symbol` → still infers (A's
  fallback intact).
- A futures option gains day precision where A gave only a month.

**Verification:** An unsettled FOP shows the same expiry as the settled row for
the same contract.

---

### U4. Fix D — derive Open/Close (Action) from realized P&L

**Goal:** Unsettled rows show the **Action** (Open/Close) — and thus
cover-vs-add when combined with Side — instead of a blank `—`.

**Critical finding (drove the approach).** The real-time `ib_async.Execution`
object has **no `openClose` and no `positionEffect` field**. The Open/Close shown
on settled rows comes from **FlexQuery**'s authoritative `Open/CloseIndicator`,
not from TWS. IBKR does not stamp a fill with cover-vs-add — it is a FIFO
position-netting determination made post-trade. So for real-time rows the
indicator must be **derived**, not captured.

**Dependencies:** none. No migration — `realized_pnl` already exists on
`LiveExecution`. Synergizes with C: `combo_summary` rows resolve to "Roll".

**Files:**

- `src/api/routers/trades.py` — add `_lifecycle_from_live_execution(le)` and set
  `trade_lifecycle=...` in `_unsettled_live_executions` (currently hardcoded
  `None`).

**Approach:** `exec_role == "combo_summary"` → "Roll" (mirroring
`_trade_lifecycle_from_execution`); else non-zero, non-null `realized_pnl` →
"Close"; else "Open". IBKR reports non-zero `realizedPNL` only when a fill
_reduces_ a position. Do **not** route through the raw-based
`_trade_lifecycle_from_execution` — the live row has no `openClose` to read.

**Best-effort, by design.** FlexQuery's authoritative indicator supersedes this
at settlement, and a rare exact-breakeven scratch close misclassifies as Open.
Document that inline. **Alternative considered:** position-netting against
`live_positions` — more precise but needs the pre-fill (start-of-day) position
and sequential replay; deferred unless the P&L proxy proves insufficient.

**Test scenarios:**

- BUY with non-zero `realized_pnl` → "Close" (buy to cover a short).
- BUY with `realized_pnl=0.0` → "Open" (buy to add).
- SELL with `realized_pnl=0.0` → "Open" (sell to open a short).
- SELL with non-zero `realized_pnl` → "Close" (sell to exit a long).
- `realized_pnl=None` → "Open".
- `combo_summary` row → "Roll" regardless of realized P&L.
- Regression: a standalone row's display and role are unaffected.

**Execution note:** Exact `!= 0` is fine unless tiny non-zero residuals are
observed in practice; only then guard with an epsilon.

**Verification:** Unsettled rows show Open/Close consistent with the realized-P&L
column, and flip to the FlexQuery-authoritative indicator once settled.

---

## Scope boundaries

**Out of scope:** the Expired action for unsettled rows (see above); any change
to the settled/FlexQuery pipelines, which are the parity _reference_, not a
target; realized-P&L, tagging, or dedup behavior of unsettled rows.

**Frontend:** none needed. `TradesTable.tsx` already renders `contract_display`,
the role badge, and the Action column from the existing API contract — B and D
only need correct values fed to it.
