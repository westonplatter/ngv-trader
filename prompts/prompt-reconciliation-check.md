# Intraday → Settled Reconciliation Check Prompt

Run this the morning **after** a session where live TWS fills (and/or live
trade-group tags) were created, once the overnight FlexQuery sync has re-imported
the now-settled data. It verifies that today's live overlay folded cleanly into
the settled record — no double-counted PnL, no orphaned tags, no lingering
net-closed positions.

All checks are **read-only `SELECT`s** — never write to reconcile (schema/data
changes go through migrations; state fixes go through re-running the jobs below).

## Context: the invariants being verified

Reconciliation rests on one stable key — **`ib_exec_id`** — shared by the live
TWS fill and the settled FlexQuery record. The guarantees:

1. **Settled is idempotent.** `trade_executions` upserts on `ib_exec_id`
   (`trade_sync_flexquery.py`), so re-import updates in place, never duplicates.
2. **Settled wins for realized PnL.** A live fill whose `ib_exec_id` is already
   settled is excluded at read time (`intraday_overlay.dedupe_live_realized`) and
   physically purged on the next intraday run (`intraday_sync_tws._purge_settled`).
3. **Tags carry over.** A provisional `trade_group_live_executions` link folds
   onto the canonical `trade_group_executions` and is deleted, via
   `group_link_carryover.carry_over_settled_group_links` — run by **both** the
   FlexQuery trade sync and the intraday purge (so it happens even if the overlay
   never runs again).
4. **Positions are snapshot-replaced.** `positions` (per account, FlexQuery) and
   `live_positions` (per account, each intraday run) are delete-then-insert, so
   net-closed instruments disappear.

If all four hold, the checks below return empty / zero.

## Checks (expected result in each heading)

### 1. Orphaned live tags — expect 0 rows

A live tag whose fill has settled but was **not** carried over. Should be empty:
carry-over runs inside the FlexQuery sync.

```sql
SELECT tgle.ib_exec_id, tgle.trade_group_id
FROM trade_group_live_executions tgle
JOIN trade_executions te ON te.ib_exec_id = tgle.ib_exec_id
LEFT JOIN trade_group_executions tge ON tge.trade_execution_id = te.id
WHERE tge.id IS NULL;
```

Non-empty → carry-over didn't run or failed. Re-run the FlexQuery **trade** sync
(it calls `carry_over_settled_group_links` unconditionally), then re-check.

### 2. Double-tagged fills — expect 0 rows

The same fill linked live **and** settled to a group (would double-count in
group views until the live link is dropped). Should be empty after carry-over,
which deletes the live link.

```sql
SELECT te.ib_exec_id
FROM trade_executions te
JOIN trade_group_executions tge ON tge.trade_execution_id = te.id
JOIN trade_group_live_executions tgle ON tgle.ib_exec_id = te.ib_exec_id;
```

Non-empty → a live link survived carry-over. Re-run FlexQuery trade sync or an
intraday sync (its purge deletes settled live links). Read-time totals already
dedupe, so this is a cleanup issue, not a reported-number issue.

### 3. Settled live executions still in `live_executions` — expect 0 (harmless if not)

Live fills whose `ib_exec_id` has settled should have been purged.

```sql
SELECT le.ib_exec_id, le.con_id, le.realized_pnl
FROM live_executions le
JOIN trade_executions te ON te.ib_exec_id = le.ib_exec_id;
```

Non-empty is **not** a data-integrity bug — read paths exclude these via
`dedupe_live_realized` — but it means no intraday sync has run since settlement.
Run one intraday sync to purge; then this returns empty.

### 4. Duplicate settled executions — expect 0 rows

`ib_exec_id` is unique, so re-import must not duplicate. Should be empty.

```sql
SELECT ib_exec_id, COUNT(*)
FROM trade_executions
GROUP BY ib_exec_id
HAVING COUNT(*) > 1;
```

Non-empty → the idempotency key broke (investigate `ib_exec_id` derivation,
especially combos below). This *would* double-count — treat as high priority.

### 5. Combo sentinel ids — spot-check

Combos have no IBKR `execId`; the sync synthesizes `f"{order_id}.combo"`
(`trade_sync_flexquery.py`). Confirm the live and settled sides agree so combos
dedupe like single-leg fills.

```sql
SELECT ib_exec_id FROM trade_executions   WHERE ib_exec_id LIKE '%.combo';
SELECT ib_exec_id FROM live_executions    WHERE ib_exec_id LIKE '%.combo';
```

A `.combo` id present live but absent (or differently formatted) settled is the
most likely place a combo double-counts. Cross-check by `order_id`.

### 6. Net-closed positions lingering — expect them gone

An instrument you flattened yesterday should be absent from **both** the fresh
`positions` snapshot and `live_positions` (or present with `position = 0`).

```sql
SELECT p.account_id, p.con_id, p.position
FROM positions p
WHERE p.position <> 0
  AND NOT EXISTS (
    SELECT 1 FROM live_positions lp
    WHERE lp.account_id = p.account_id AND lp.con_id = p.con_id
  );
```

For accounts that synced live, such rows are treated as net-closed and dropped at
read time; if the settled snapshot still shows a stale nonzero position, re-run
the FlexQuery **position** sync (it delete-then-inserts per account).

## PnL sanity cross-check

For a group that had live realized PnL yesterday, confirm today's settled group
realized PnL ≈ yesterday's (settled + intraday-realized) shown in the overlay,
within commissions/rounding. A large jump usually means a fill counted twice
(check 4/5) or a tag lost (check 1). `GET /trade-groups/{id}/executions` returns
both the settled and `intraday_*` figures for the comparison.

## Marks & greeks — no action needed

`latest_quote` and `latest_option_metrics` are `con_id`-keyed latest-state caches
with no settled/unsettled notion; they're overwritten each sync and read only for
held positions. A closed position drops out of `live_positions`, so a stale
quote/greek row is simply never read. Nothing to reconcile here.

## Summary: green looks like

Checks 1, 2, 4, 6 return empty; check 3 empty after an intraday run; check 5
shows matching `.combo` ids on both sides; group PnL reconciles within
commissions. If any check is non-empty, the remediation is always **re-run a
job** (FlexQuery trade/position sync, or an intraday sync) — never a manual
`UPDATE`/`DELETE`.
