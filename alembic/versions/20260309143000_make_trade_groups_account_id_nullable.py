"""make trade_groups.account_id nullable

Revision ID: d4h6j8l0n2p4
Revises: c3e5g7i9k1m3
Create Date: 2026-03-09 14:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4h6j8l0n2p4"
down_revision: Union[str, Sequence[str], None] = "c3e5g7i9k1m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "trade_groups",
        "account_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "trade_groups",
        "account_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
