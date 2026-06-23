"""merge intraday overlay and activated products heads

Revision ID: 3b816471d945
Revises: a1c3e5g7i9k1, 3b28da5d71f9
Create Date: 2026-06-22 20:43:53.513198

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3b816471d945"
down_revision: Union[str, Sequence[str], None] = ("a1c3e5g7i9k1", "3b28da5d71f9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
