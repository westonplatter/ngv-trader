"""add mark price and unrealized pnl to positions

Revision ID: e22ccdc3f6de
Revises: 07f252367c32
Create Date: 2026-05-13 23:42:18.196290

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e22ccdc3f6de"
down_revision: Union[str, Sequence[str], None] = "07f252367c32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("mark_price", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("position_value", sa.Float(), nullable=True))
    op.add_column("positions", sa.Column("fifo_pnl_unrealized", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "fifo_pnl_unrealized")
    op.drop_column("positions", "position_value")
    op.drop_column("positions", "mark_price")
