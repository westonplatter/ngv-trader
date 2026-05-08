"""widen ib_order_id and ib_perm_id to bigint

Revision ID: 22ce4113fb3c
Revises: 683ce2f42f99
Create Date: 2026-05-07 21:21:31.080992

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22ce4113fb3c"
down_revision: Union[str, Sequence[str], None] = "683ce2f42f99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("trades", "trade_executions"):
        op.alter_column(table, "ib_order_id", type_=sa.BigInteger(), existing_nullable=True)
        op.alter_column(table, "ib_perm_id", type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    for table in ("trades", "trade_executions"):
        op.alter_column(table, "ib_perm_id", type_=sa.Integer(), existing_nullable=True)
        op.alter_column(table, "ib_order_id", type_=sa.Integer(), existing_nullable=True)
