# Postgres Snapshots Before Big DB Changes

Take a snapshot before any DB change that is hard to reverse: destructive or
data-mutating migrations, backfills, `alembic downgrade` on prod, or bulk
deletes. Additive-only migrations (new tables/columns, nullable) generally don't
need one, but snapshot anyway when unsure — it's cheap.

The working DB is `ngtrader_pro_prod` (see [project memory] — there is no
separate dev DB). Connection vars (`DB_HOST/PORT/USER/PASSWORD/NAME`) resolve
from `op://` references, so every command runs under `op run`.

## Take a snapshot

```bash
SNAP_DIR="$HOME/ngv-trader-db-snapshots"; mkdir -p "$SNAP_DIR"
OUT="$SNAP_DIR/ngtrader_pro_prod-$(date +%Y%m%d-%H%M%S).dump"
ENV=prod op run --env-file=.env.prod -- bash -c '
  PGPASSWORD="$DB_PASSWORD" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    -d "${DB_NAME:-ngtrader_pro_prod}" -Fc -f "'"$OUT"'"'
```

`-Fc` is the compressed custom format (restorable, selective). Snapshots live
outside the repo (`~/ngv-trader-db-snapshots/`) — never commit dump files.

## Verify it

```bash
pg_restore -l "$OUT" | grep -c 'TABLE DATA'   # sanity: table count > 0
```

## Restore

```bash
# whole DB (into an empty/clean target)
ENV=prod op run --env-file=.env.prod -- bash -c '
  PGPASSWORD="$DB_PASSWORD" pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    -d "$DB_NAME" --clean --if-exists "'"$OUT"'"'

# single table: add  -t <table>   (and --data-only to keep current schema)
```

## Recommended flow for a risky migration

1. Snapshot + verify (above).
2. Apply the migration; confirm round-trip with `alembic downgrade -1 && alembic upgrade head`.
3. Spot-check affected tables.
4. Keep the dump until the change is merged and confirmed in use.

[project memory]: ENV=prod is the default working environment; secrets via `op run`.
