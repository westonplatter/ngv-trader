"""add meta_yaml to trade_groups

Revision ID: a3bf4e84435e
Revises: 01711d684634
Create Date: 2026-07-11 01:53:01.912500

Free-form YAML "management spec" attached to a trade group. Holds the raw,
human-authored YAML source verbatim (comments and ordering preserved) so it
round-trips exactly. The parsed structure is exposed by the API at read time;
recognized blocks (delta/date/profit targets) let an agent read intent while
arbitrary keys pass through. Additive, nullable, no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3bf4e84435e'
down_revision: Union[str, Sequence[str], None] = '01711d684634'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "trade_groups",
        sa.Column("meta_yaml", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("trade_groups", "meta_yaml")
