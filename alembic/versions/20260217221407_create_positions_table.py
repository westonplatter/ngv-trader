"""create positions table

Revision ID: a6c9b6424a2f
Revises:
Create Date: 2026-02-17 22:14:07.134510

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c9b6424a2f"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account", sa.String, nullable=False),
        sa.Column("con_id", sa.Integer, nullable=False),
        sa.Column("symbol", sa.String),
        sa.Column("sec_type", sa.String),
        sa.Column("exchange", sa.String),
        sa.Column("primary_exchange", sa.String),
        sa.Column("currency", sa.String),
        sa.Column("local_symbol", sa.String),
        sa.Column("trading_class", sa.String),
        sa.Column("last_trade_date", sa.String),
        sa.Column("strike", sa.Float),
        sa.Column("right", sa.String),
        sa.Column("multiplier", sa.String),
        sa.Column("position", sa.Float, nullable=False),
        sa.Column("avg_cost", sa.Float, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account", "con_id", name="uq_account_con_id"),
    )


def downgrade() -> None:
    op.drop_table("positions")
