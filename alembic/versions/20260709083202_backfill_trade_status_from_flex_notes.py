"""backfill_trade_status_from_flex_notes

Data migration: relabel historical trades whose canonical fills are all
expirations / assignments / exercises. Before this, every settled trade with
fills was hardcoded to status='filled'. The ingest path now derives status from
the IBKR Flex notes codes ('Ep', 'A', 'Ex'); this backfills the same derivation
onto trades ingested earlier.

Self-contained: the classification is duplicated here (not imported from
src.services) so this migration's behavior is frozen even if that code evolves.

Revision ID: 4b2386b53758
Revises: 01711d684634
Create Date: 2026-07-09 08:32:02.476127

"""

import re
from collections import defaultdict
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b2386b53758"
down_revision: Union[str, Sequence[str], None] = "01711d684634"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NOTES_SPLIT = re.compile(r"[;,\s]+")
# Flex notes code -> non-fill status, priority order. Mirrors
# src.services.sync_common._NOTE_STATUS at the time of writing.
_NOTE_STATUS: tuple[tuple[str, str], ...] = (
    ("EP", "expired"),
    ("A", "assigned"),
    ("EX", "exercised"),
)
_SPECIAL_STATUSES = tuple(status for _code, status in _NOTE_STATUS)


def _outcome(notes: str | None) -> str:
    if not notes:
        return "filled"
    codes = {tok.upper() for tok in _NOTES_SPLIT.split(str(notes)) if tok}
    for code, status in _NOTE_STATUS:
        if code in codes:
            return status
    return "filled"


def upgrade() -> None:
    """Relabel trades whose canonical fills all share one non-fill outcome."""
    bind = op.get_bind()
    rows = bind.execute(sa.text("""
            SELECT trade_id, raw->>'notes' AS notes
            FROM trade_executions
            WHERE is_canonical = true
            """)).fetchall()

    outcomes_by_trade: dict[int, set[str]] = defaultdict(set)
    for trade_id, notes in rows:
        outcomes_by_trade[trade_id].add(_outcome(notes))

    ids_by_status: dict[str, list[int]] = defaultdict(list)
    for trade_id, outcomes in outcomes_by_trade.items():
        if len(outcomes) == 1:
            (only,) = tuple(outcomes)
            if only in _SPECIAL_STATUSES:
                ids_by_status[only].append(trade_id)

    for status, ids in ids_by_status.items():
        bind.execute(
            sa.text("""
                UPDATE trades
                SET status = :status, updated_at = now()
                WHERE id = ANY(:ids) AND status <> :status
                """),
            {"status": status, "ids": ids},
        )


def downgrade() -> None:
    """Revert the special statuses back to 'filled'."""
    bind = op.get_bind()
    bind.execute(
        sa.text("""
            UPDATE trades
            SET status = 'filled', updated_at = now()
            WHERE status = ANY(:statuses)
            """),
        {"statuses": list(_SPECIAL_STATUSES)},
    )
