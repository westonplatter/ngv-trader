"""add tags archived_at

Revision ID: 19412730c878
Revises: e22ccdc3f6de
Create Date: 2026-06-09 21:25:26.122430

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "19412730c878"
down_revision: Union[str, Sequence[str], None] = "e22ccdc3f6de"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("tags", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tags_archived_at", "tags", ["archived_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_tags_archived_at", table_name="tags")
    op.drop_column("tags", "archived_at")
