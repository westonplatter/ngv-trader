---
title: "fix: Recover a missing opening execution for an open futures position"
type: fix
status: resolved-via-synthetic-insert
created: 2026-07-14
---

> **RESOLVED 2026-07-14 via Approach 2 (manual synthetic insert).** Flex recovery
> (Approach 1) was abandoned; a synthetic opening execution was inserted directly
> so the position could be grouped. Details in the "Executed" note under
> Approach 2. Reverse with the one-liner there if the real fill is ever recovered.

# fix: Recover a missing opening execution for an open futures position

## Summary

One account holds an **open Micro WTI Crude futures position** that **cannot be
assigned to a trade group**. Trade group membership is keyed on **executions**
(`trade_group_executions.trade_execution_id`), not on positions — a position is only assignable if at least one
`trade_executions` row exists for its `(account_id, con_id)`. For this contract
there are **zero** such rows, so the UI has nothing to attach the group to.

> Identifiers and account activity are redacted in this doc. The concrete account,
> `con_id`, quantities, prices, dates, and row ids live only in the local
> (gitignored) `scratchpad/` helper and the running app. Placeholders below:
> account = `<ACCOUNT>`, contract = `<CONID>`.

## Root cause

The opening fill was never imported. Our FlexQuery "daily" import historically
only covered a recent window (`<DAILY_START> → present`), and the fill predates
that. IBKR's Flex Web Service only serves roughly the **last 365 days**, so there
is a hard floor (`<FLEX_FLOOR>`) below which no chunk can reach.

## Approach 1 — Scoped idempotent FlexQuery backfill (in progress)

Re-import that account's older trades in **small date-ranged chunks** and let the normal
upsert (`sync_flex_trades`, keyed on `ib_exec_id`) insert only fills we don't
already have. Idempotent — safe to re-run.

Mechanism: for each chunk, `fetch_flex_report(token, daily_query_id, start, end)`
→ `sync_flex_trades(engine, account_code=<ACCOUNT>, report=report, start, end)`,
filtered to that one account. (Local driver lives in gitignored `scratchpad/`.)

### Status so far

| Window                        | Result                                                                          |
| ----------------------------- | ------------------------------------------------------------------------------- |
| `<FLEX_FLOOR> → <GAP_START>`  | ✅ imported — extended the account's history back to the Flex floor             |
| `<GAP_START> → <DAILY_START>` | ❌ **gap** — chunk failed, IBKR rate-limited (`1025: Too many failed attempts`) |
| `<DAILY_START> → present`     | already present (pre-existing daily import)                                     |

**The target `con_id` is still absent** after the successful chunks, so the fill
is **not** in the imported window. It is therefore one of:

1. **In the un-imported gap** — recoverable once the IBKR rate-limit clears.
2. **Below the Flex floor** — outside the 365-day window; **not recoverable
   via Flex** (needs an annual/activity statement export, or Approach 2).
3. **Not a regular Flex "daily" trade** (e.g. an assignment/transfer/give-up) —
   would need a different report or Approach 2.

### Next actions

1. **Wait ~20–30 min** for the IBKR `1025` lockout to clear (do not retry into a
   locked-out state — it extends the lockout).
2. **Read-only verify** the gap window first:
   ```
   op run --env-file=.env.prod -- \
     uv run python scripts/fetch_flex_trades.py --days <N> --end-date <GAP_END>
   ```
   Grep the resulting XML for the target `con_id`.
3. If present → run the scoped idempotent import for that one window; confirm a
   `trade_executions` row now exists for `(<ACCOUNT>, <CONID>)`; the position
   becomes assignable. Done.
4. If absent → the fill is pre-window / non-trade. Try an **annual statement**
   Flex query for the relevant year; if still nothing, fall back to Approach 2.

## Approach 2 — Synthetically create the execution (worst case)

If Flex genuinely cannot return the fill, insert a **single synthetic
`trade_executions` row** so the position can be grouped. This is a last resort:
it fabricates a record, so it must be clearly marked, auditable, and reversible.

Do it as an **Alembic data migration** (same pattern as the
`backfill_trade_status_from_flex_notes` migration), **not** ad-hoc SQL — DB
changes go through migrations in this repo.

### Row to create

`trade_executions` needs a parent `trades` row (`trade_id` FK). Populate from the
known facts of the open position:

| Column          | Value                        | Notes                                                               |
| --------------- | ---------------------------- | ------------------------------------------------------------------- |
| `account_id`    | `<ACCOUNT>` account id       |                                                                     |
| `con_id`        | `<CONID>`                    | from the positions table / app                                      |
| `ib_exec_id`    | `SYNTH-<con_id>-<yyyymmdd>`  | **synthetic, unique**; makes the migration idempotent and greppable |
| `exec_id_base`  | same as `ib_exec_id`         |                                                                     |
| `exec_revision` | `1`                          |                                                                     |
| `sec_type`      | `FUT`                        |                                                                     |
| `side`          | `BUY` (long)                 | match the position's direction                                      |
| `quantity`      | `<QTY>`                      | position size                                                       |
| `price`         | `<AVG_COST>`                 | the known avg cost / trade price                                    |
| `executed_at`   | best-known fill timestamp    | approximate if unknown; document the assumption                     |
| `exec_role`     | `standalone`                 |                                                                     |
| `order_ref`     | e.g. `synthetic-remediation` | audit marker                                                        |

### Executed (2026-07-14)

Inserted directly into the prod database (one transaction, ORM):

- `trades.id = <TRADE_ID>` — `data_source='manual'`,
  `order_ref='synthetic-remediation'`, status `filled`, BUY `<QTY>` @ `<AVG_COST>`.
- `trade_executions.id = <EXEC_ROW_ID>` — `ib_exec_id = SYNTH-<CONID>-<YYYYMMDD>`,
  `data_source='manual'`, `raw.synthetic = true`, side BUY, qty `<QTY>`,
  price `<AVG_COST>`.
- `executed_at` — **placeholder** (real fill date unknown; = the day the position
  was first observed open). Correct if recovered.

**Reverse** (if the real fill is later imported, to avoid double-counting):

```sql
DELETE FROM trade_executions WHERE ib_exec_id = 'SYNTH-<CONID>-<YYYYMMDD>';
DELETE FROM trades WHERE id = <TRADE_ID>;  -- only if no other executions reference it
```

(Also remove any trade-group assignment made against that exec row first. The
concrete account, `con_id`, row ids and synthetic `ib_exec_id` are recorded in
`scratchpad/synthetic-execution-reversal.md`, gitignored to avoid leaking it.)

### Caveats

- **Not real IBKR data** — flag it in the migration docstring and (if available)
  an `order_ref`/note so it's never mistaken for a genuine fill or double-counted
  against a later real import.
- **Idempotent key**: the synthetic `ib_exec_id` means a later _real_ Flex import
  of the same fill will land under a _different_ `ib_exec_id` and could
  double-count. Before/after any successful Flex recovery, delete the synthetic
  row (its stable `SYNTH-…` id makes this a one-liner).
- **P&L impact**: a synthetic opening execution feeds realized/unrealized
  aggregates; verify group and account P&L look right afterward.
- Prefer Approach 1 in every case where Flex can still return the fill.

## Decision

Exhaust Approach 1 (gap retry → annual statement) before Approach 2. Approach 2
is only for the case where the fill is permanently unreachable via Flex.
