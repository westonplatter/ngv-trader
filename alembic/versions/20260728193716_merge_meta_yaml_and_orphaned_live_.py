"""merge meta_yaml and orphaned live execution cleanup heads

Two independent branches off ``01711d684634`` shipped concurrently: the additive
``trade_groups.meta_yaml`` column (a3bf4e84435e) and the one-time phantom
``live_executions`` cleanup (3f9a1c7d5e02). They touch disjoint tables, so this
is a pure bookkeeping merge with no schema or data changes of its own.

Revision ID: 2bc294c04f36
Revises: a3bf4e84435e, 3f9a1c7d5e02
Create Date: 2026-07-28 19:37:16.901812

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2bc294c04f36"
down_revision: Union[str, Sequence[str], None] = ("a3bf4e84435e", "3f9a1c7d5e02")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
