"""add limit_price to orders

Revision ID: a6c51b7d2f44
Revises: 8a3de6b9f112
Create Date: 2026-02-25 08:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6c51b7d2f44"
down_revision: Union[str, Sequence[str], None] = "8a3de6b9f112"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("limit_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "limit_price")
