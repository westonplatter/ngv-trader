"""merge price_magnifier and semantic_fact_views heads

Revision ID: 0a388cb95eb0
Revises: d58cc2d31128, f1b3d5a7c9e2
Create Date: 2026-07-03 06:48:09.278367

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0a388cb95eb0'
down_revision: Union[str, Sequence[str], None] = ('d58cc2d31128', 'f1b3d5a7c9e2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
