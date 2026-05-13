"""rename job_type tws flexquery

Backfills existing jobs rows so the persisted job_type strings match the new
JOB_TYPE_* constants introduced when Flex Query became the only active sync
path. All four rewrites run in a single transaction.

Revision ID: 07f252367c32
Revises: 22ce4113fb3c
Create Date: 2026-05-13 08:09:43.397034

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "07f252367c32"
down_revision: Union[str, Sequence[str], None] = "22ce4113fb3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_UPGRADE_MAPPING = {
    "positions.sync": "positions.sync.tws",
    "positions.flex_sync": "positions.sync.flexquery",
    "trades.sync": "trades.sync.tws",
    "trades.flex_sync": "trades.sync.flexquery",
}


def upgrade() -> None:
    bind = op.get_bind()
    for old_value, new_value in _UPGRADE_MAPPING.items():
        bind.execute(
            sa.text("UPDATE jobs SET job_type = :new WHERE job_type = :old"),
            {"new": new_value, "old": old_value},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for old_value, new_value in _UPGRADE_MAPPING.items():
        bind.execute(
            sa.text("UPDATE jobs SET job_type = :old WHERE job_type = :new"),
            {"new": new_value, "old": old_value},
        )
