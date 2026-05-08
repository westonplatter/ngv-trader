"""add as_of_date to positions

Revision ID: 6b5e1576ec39
Revises: 1a9d2390bd8e
Create Date: 2026-05-07 20:42:09.891409

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b5e1576ec39"
down_revision: Union[str, Sequence[str], None] = "1a9d2390bd8e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "positions",
        sa.Column("as_of_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("positions", "as_of_date")
