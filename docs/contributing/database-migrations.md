---
topics: ["database", "alembic", "migrations", "ops"]
code_dirs_or_files:
  ["alembic/", "alembic.ini", "Taskfile.yaml", "src/models.py"]
description: The migrations-only rule for all database state, how to run and author Alembic migrations through the Taskfile, and when to snapshot first.
---

# Database Changes

## No ad-hoc DB changes — migrations only

**Every change to database state (schema, views, indexes, constraints, seed/backfill
data) MUST go through an Alembic migration.** Never apply DDL or data changes to a
database directly — no `psql`/`CREATE`/`ALTER`/`DROP`/`UPDATE` run by hand, no
`CREATE TEMP VIEW` to "just check" against a real DB, no ORM one-off scripts that
mutate. This includes the semantic-layer `v_*` views. Migrations are the only
reviewable, reversible, reproducible record of DB state. Read-only `SELECT`s for
inspecting data are fine; anything that writes or defines structure is a migration.

## Running migrations

Migrations are driven through the Taskfile, which auto-loads `.env.<ENV>`. Use the
task command, not raw `alembic`:

- Prod: `task migrate ENV=prod`
- Dev: `task migrate ENV=dev`

"Run the migrations in prod" means `task migrate ENV=prod`. No `op run` wrapper is
needed — the DB URL is built from plain `DB_HOST`/`DB_USER`/`DB_PASSWORD`, not
`op://` secrets.

Related:

- `task migrate:down` — downgrade one revision
- `task migrate:new -- "desc"` — autogenerate a new revision
- `task validate` — validate the environment

## Authoring migrations

Generate the file with `task migrate:new -- "<desc>"`, then edit only the docstring,
mapping constants, and `upgrade()`/`downgrade()` bodies. Never hand-author a revision
or touch the auto-assigned `revision`/`down_revision` — hand-picked IDs collide with
existing ones.

## Snapshots

Before any hard-to-reverse DB change (destructive/data-mutating migration, backfill,
prod `downgrade`, bulk delete), take a Postgres snapshot first. See
[db-snapshots.md](../db-snapshots.md) for the snapshot/verify/restore commands and the
recommended flow.

## Tests

The pytest suite migrates a dedicated `ngv_trader_test` database to head and checks
that migrations cover every model table. See
[validation.md](validation.md#python-tests).
