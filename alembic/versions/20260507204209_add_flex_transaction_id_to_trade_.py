"""add flex_transaction_id to trade_executions

Revision ID: 1a9d2390bd8e
Revises: 790b1dac7d8a
Create Date: 2026-05-07 20:42:09.499540

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a9d2390bd8e"
down_revision: Union[str, Sequence[str], None] = "790b1dac7d8a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "trade_executions",
        sa.Column("flex_transaction_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_trade_executions_flex_transaction_id",
        "trade_executions",
        ["flex_transaction_id"],
        unique=True,
        postgresql_where=sa.text("flex_transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_trade_executions_flex_transaction_id",
        table_name="trade_executions",
    )
    op.drop_column("trade_executions", "flex_transaction_id")
