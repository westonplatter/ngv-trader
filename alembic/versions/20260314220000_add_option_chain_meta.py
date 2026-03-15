"""add option_chain_meta table

Revision ID: e5i7k9m1o3q5
Revises: d4h6j8l0n2p4
Create Date: 2026-03-14 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5i7k9m1o3q5"
down_revision: Union[str, Sequence[str], None] = "d4h6j8l0n2p4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "option_chain_meta",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("sec_type", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=False),
        sa.Column("trading_class", sa.String(), nullable=False),
        sa.Column("underlying_con_id", sa.Integer(), nullable=False),
        sa.Column("expiration", sa.String(), nullable=False),
        sa.Column("strike", sa.Float(), nullable=False),
        sa.Column("right", sa.String(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol",
            "trading_class",
            "expiration",
            "strike",
            "right",
            name="uq_option_chain_meta_spec",
        ),
    )
    op.create_index(
        "ix_option_chain_meta_lookup",
        "option_chain_meta",
        ["symbol", "underlying_con_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_option_chain_meta_lookup", table_name="option_chain_meta")
    op.drop_table("option_chain_meta")
