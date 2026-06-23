"""add trade_group_positions table (direct position -> trade group link)

Revision ID: c4f1a9b2d3e6
Revises: 3b816471d945
Create Date: 2026-06-23 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1a9b2d3e6"
down_revision: Union[str, Sequence[str], None] = "3b816471d945"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "trade_group_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_group_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("con_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("sec_type", sa.Text(), nullable=True),
        sa.Column("local_symbol", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trade_group_id"], ["trade_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("account_id", "con_id", name="uq_trade_group_positions_account_con"),
    )
    op.create_index("ix_trade_group_positions_group", "trade_group_positions", ["trade_group_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_trade_group_positions_group", table_name="trade_group_positions")
    op.drop_table("trade_group_positions")
