---
title: "feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery"
type: feat
status: complete
created: 2026-07-08
completed: 2026-08-01
---

# feat: Bring unsettled TWS live executions to contract-display parity with FlexQuery

Unsettled executions from the real-time TWS (intraday) feed rendered with less
information than settled FlexQuery rows. Four layered fixes; **all shipped**.

| Fix   | Gap                                 | Status                             |
| ----- | ----------------------------------- | ---------------------------------- |
| **A** | contract month/expiry missing       | **shipped** 2026-07-28 (`b28e48c`) |
| **B** | expiry not authoritative (inferred) | **shipped** 2026-08-01             |
| **C** | combo/leg relationship lost         | **shipped** 2026-07-28 (`1522017`) |
| **D** | Action (Open/Close) blank           | **shipped** 2026-08-01             |

Shipped behavior lives in the subsystem docs, not here:
[core/intraday-tws-overlay.md](../core/intraday-tws-overlay.md) (combo roles,
order key, unit tagging, and the **Display parity with settled rows** section
covering B and D) and
[trades-and-executions-sync.md](../trades-and-executions-sync.md) (shared
`exec_role` vocabulary; FlexQuery as the authoritative Open/Close source).

**Also unblocked (and shipped):** C's order key was the hard dependency of the
leg-anchored purge in the bag-summary live-reconciliation work, which landed
2026-08-01 as Option 1 rather than the timestamp-heuristic Option 2.

**Not achievable from this feed:** the **Expired** action. An option expiration
produces no execution/fill, so it never appears in the real-time TWS fills feed —
it is sourced from FlexQuery only. Unsettled rows will therefore never show
Expired; a data-source limitation, not a bug.

## What landed for B and D

- **B** — `live_executions.last_trade_date` (migration `701c3434b8dc`, additive
  and nullable, no backfill) stores IBKR's raw
  `lastTradeDateOrContractMonth`; `_live_execution_values` captures it and
  `_live_contract_display` feeds it into `_contract_display_from_raw`, where a
  stored expiry already outranked local-symbol inference. Closes the residual
  where futures options showed only a month.
- **D** — `_lifecycle_from_live_execution` in `src/api/routers/trades.py` derives
  the Action from realized P&L (`combo_summary` → Roll, non-zero
  `realized_pnl` → Close, else Open) and fills the previously-hardcoded `None`
  `trade_lifecycle`. Derived rather than captured because the real-time
  `Execution` object carries no `openClose`/`positionEffect`.

**Deferred alternative for D:** position-netting against `live_positions` —
more precise, but needs the pre-fill (start-of-day) position and sequential
replay. Revisit only if the P&L proxy proves insufficient in practice.

**Frontend:** none needed. `TradesTable.tsx` already rendered
`contract_display`, the role badge, and the Action column from the existing API
contract — B and D only fed it correct values.
