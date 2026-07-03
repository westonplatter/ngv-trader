"""add price_magnifier to contracts

Revision ID: 299393aba4a0
Revises: c4f1a9b2d3e6
Create Date: 2026-06-23 23:20:24.579479

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "299393aba4a0"
down_revision: Union[str, Sequence[str], None] = "c4f1a9b2d3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the price_magnifier add is intended here; autogenerate also surfaced
    # pre-existing index/FK drift on unrelated tables, which is deliberately
    # excluded from this migration.
    op.add_column("contracts", sa.Column("price_magnifier", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("contracts", "price_magnifier")
