---
title: Data migration importing live service code cannot build a fresh database
date: 2026-08-07
category: logic-errors
module: alembic
problem_type: logic_error
component: migration
symptoms:
  - "`alembic upgrade head` on an empty database fails with `UndefinedColumn: column live_executions.ib_perm_id does not exist`"
  - "Migrations run clean against dev/prod but the chain cannot be replayed from scratch"
  - "A new test/CI database cannot be provisioned even though every revision is already applied in prod"
root_cause: logic_error
resolution_type: code_fix
severity: medium
tags:
  - alembic
  - migrations
  - data-migration
  - fresh-database
  - orm-coupling
  - testing
related_components:
  - database
  - test_suite
---

# Data migration importing live service code cannot build a fresh database

## Problem

`3f9a1c7d5e02` (`cleanup_orphaned_live_executions`) is a one-time data migration that calls the shipped `reconcile_orphaned_live_executions()` from `src/services/live_reconcile.py`. That function queries the **current** `LiveExecution` ORM model, which by now includes columns added by _later_ revisions (`ib_perm_id`, `exec_role`, `last_trade_date`).

Replaying the chain on an empty database therefore dies mid-way:

```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn)
column live_executions.ib_perm_id does not exist
```

Dev and prod never saw this — the revision was applied back when the model and the schema still agreed. The breakage only surfaced when the new pytest suite (`task test`) provisioned `ngv_trader_test` from zero.

## Root Cause

A migration is a snapshot of intent at one point in the chain; live application code is not. The moment a migration imports app code, its behavior silently changes every time that code evolves — and the schema it runs against is _older_ than the model that code expects. The revision's own docstring even asserted the correct invariant ("on a fresh database `live_executions` is empty so it is a harmless no-op"), but nothing enforced it: the query still had to be _compiled and executed_ to discover there were no rows.

## Fix

Make the no-op claim structural — return before touching the ORM when the table is empty:

```python
def upgrade() -> None:
    bind = op.get_bind()
    # Fresh database: the reconcile below is a no-op by definition. Skip it —
    # the shipped reconcile reads columns added by LATER revisions.
    if bind.execute(sa.text("SELECT 1 FROM live_executions LIMIT 1")).first() is None:
        return
    ...
```

Prod is unaffected (the revision is already stamped); only from-scratch builds change behavior, and there they now succeed instead of failing.

## Takeaways

- **Prefer frozen SQL/`sa.table()` literals in data migrations.** Import live service code only when the migration is a genuinely one-time cleanup of known rows — and then guard it so an empty table short-circuits before any ORM query is compiled.
- **A docstring is not a guard.** "This is a no-op on a fresh DB" must be an early `return`, not a comment.
- **Only a from-scratch build catches this class of bug.** Migrations that pass against a long-lived dev/prod database prove nothing about replayability. `task test` provisions `ngv_trader_test` from empty on every fresh checkout, so the migration chain is now exercised end-to-end.
- **Same risk exists elsewhere.** Any other data migration importing `src.services.*` has the same fragility; the test suite will surface them the next time the test database is dropped and rebuilt.
