"""add trade_group_live_executions (group assignment for unsettled TWS fills)

Keyed by ib_exec_id so a live fill can be assigned to a trade group intraday,
before it settles into trade_executions. On settlement the assignment is carried
over into trade_group_executions and the live link is dropped.

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
        "trade_group_live_executions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_group_id", sa.Integer(), nullable=False),
        sa.Column("ib_exec_id", sa.Text(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("con_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["trade_group_id"], ["trade_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ib_exec_id", name="uq_trade_group_live_executions_ib_exec_id"),
    )
    op.create_index("ix_trade_group_live_executions_group", "trade_group_live_executions", ["trade_group_id"], unique=False)
    op.create_index(
        "ix_trade_group_live_executions_account_con",
        "trade_group_live_executions",
        ["account_id", "con_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_trade_group_live_executions_account_con", table_name="trade_group_live_executions")
    op.drop_index("ix_trade_group_live_executions_group", table_name="trade_group_live_executions")
    op.drop_table("trade_group_live_executions")
