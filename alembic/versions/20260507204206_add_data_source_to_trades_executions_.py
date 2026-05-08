"""add data_source to trades executions positions

Revision ID: 790b1dac7d8a
Revises: f6j8l0n2p4r6
Create Date: 2026-05-07 20:42:06.189595

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "790b1dac7d8a"
down_revision: Union[str, Sequence[str], None] = "f6j8l0n2p4r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("trades", "trade_executions", "positions"):
        op.add_column(
            table,
            sa.Column(
                "data_source",
                sa.Text(),
                nullable=False,
                server_default="tws",
            ),
        )


def downgrade() -> None:
    for table in ("positions", "trade_executions", "trades"):
        op.drop_column(table, "data_source")
