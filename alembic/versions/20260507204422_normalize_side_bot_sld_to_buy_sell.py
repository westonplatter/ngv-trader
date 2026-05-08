"""normalize side bot sld to buy sell

Revision ID: 683ce2f42f99
Revises: 01ca3f6d2394
Create Date: 2026-05-07 20:44:22.149834

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "683ce2f42f99"
down_revision: Union[str, Sequence[str], None] = "01ca3f6d2394"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


BATCH_SIZE = 5000
_ALLOWED_TABLES = frozenset({"trades", "trade_executions"})


def _batched_update(table: str, mapping: dict[str, str]) -> None:
    if table not in _ALLOWED_TABLES:
        raise ValueError(f"Refusing to run migration against unexpected table: {table!r}")
    bind = op.get_bind()
    max_id = bind.execute(sa.text(f"SELECT COALESCE(MAX(id), 0) FROM {table}")).scalar() or 0  # noqa: S608
    for old_value, new_value in mapping.items():
        start = 1
        while start <= max_id:
            end = start + BATCH_SIZE - 1
            bind.execute(
                sa.text(f"UPDATE {table} SET side = :new WHERE side = :old AND id BETWEEN :start AND :end"),  # noqa: S608
                {"new": new_value, "old": old_value, "start": start, "end": end},
            )
            start = end + 1


def upgrade() -> None:
    forward = {"BOT": "BUY", "SLD": "SELL"}
    _batched_update("trades", forward)
    _batched_update("trade_executions", forward)


def downgrade() -> None:
    reverse = {"BUY": "BOT", "SELL": "SLD"}
    _batched_update("trades", reverse)
    _batched_update("trade_executions", reverse)
