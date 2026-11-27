"""order last seen at

`orders.last_seen_at` records when a broker fetch last reported the order. The stale
sweep moves a working order the broker no longer reports to `reconcile_required` when
it was last seen before the fetch started. NULL means never seen by a broker fetch.

Raw op calls only, so the migration does not depend on live service code.

Revision ID: c5d8a1e3f702
Revises: 9b4c2e7a1d35
Create Date: 2026-11-27 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d8a1e3f702"
down_revision: Union[str, Sequence[str], None] = "9b4c2e7a1d35"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "last_seen_at")
