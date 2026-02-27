"""add combo_positions and combo_position_legs tables

Revision ID: c7d82e4f1a33
Revises: a6c51b7d2f44
Create Date: 2026-02-26 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d82e4f1a33"
down_revision: Union[str, None] = "a6c51b7d2f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "combo_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="cpapi"),
        sa.Column("combo_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            "source",
            "combo_key",
            name="uq_combo_positions_account_source_key",
        ),
        sa.Index("ix_combo_positions_account_fetched", "account_id", "fetched_at"),
    )

    op.create_table(
        "combo_position_legs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "combo_position_id",
            sa.Integer(),
            sa.ForeignKey("combo_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("con_id", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=True),
        sa.Column("position", sa.Float(), nullable=True),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("market_value", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=True),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "combo_position_id",
            "con_id",
            name="uq_combo_leg_position_conid",
        ),
        sa.Index("ix_combo_position_legs_con_id", "con_id"),
    )


def downgrade() -> None:
    op.drop_table("combo_position_legs")
    op.drop_table("combo_positions")
