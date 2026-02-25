"""add jobs archived_at

Revision ID: f7a3c1d8e2b4
Revises: e4f2a9b56c80
Create Date: 2026-02-19 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f7a3c1d8e2b4"
down_revision: Union[str, Sequence[str], None] = "e4f2a9b56c80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_archived_at", "jobs", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_archived_at", table_name="jobs")
    op.drop_column("jobs", "archived_at")
