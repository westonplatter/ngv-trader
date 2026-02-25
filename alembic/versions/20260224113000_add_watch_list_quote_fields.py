"""add quote fields to watch_list_instruments

Revision ID: 8a3de6b9f112
Revises: f5c16fa2c5cc
Create Date: 2026-02-24 11:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a3de6b9f112"
down_revision: Union[str, Sequence[str], None] = "f5c16fa2c5cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "watch_list_instruments",
        sa.Column("bid_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "watch_list_instruments",
        sa.Column("ask_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "watch_list_instruments",
        sa.Column("close_price", sa.Float(), nullable=True),
    )
    op.add_column(
        "watch_list_instruments",
        sa.Column("quote_as_of", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("watch_list_instruments", "quote_as_of")
    op.drop_column("watch_list_instruments", "close_price")
    op.drop_column("watch_list_instruments", "ask_price")
    op.drop_column("watch_list_instruments", "bid_price")
