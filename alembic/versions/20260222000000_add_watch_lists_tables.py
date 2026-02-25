"""add watch_lists and watch_list_instruments tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-22 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watch_lists",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
    )

    op.create_table(
        "watch_list_instruments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("watch_list_id", sa.Integer(), nullable=False),
        sa.Column("con_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("sec_type", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("local_symbol", sa.String(), nullable=True),
        sa.Column("trading_class", sa.String(), nullable=True),
        sa.Column("contract_month", sa.String(), nullable=True),
        sa.Column("contract_expiry", sa.String(), nullable=True),
        sa.Column("multiplier", sa.String(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("right", sa.String(), nullable=True),
        sa.Column("primary_exchange", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("watch_list_id", "con_id", name="uq_watch_list_id_con_id"),
        sa.Index(
            "ix_watch_list_instruments_lookup",
            "watch_list_id",
            "symbol",
            "sec_type",
        ),
    )


def downgrade() -> None:
    op.drop_table("watch_list_instruments")
    op.drop_table("watch_lists")
