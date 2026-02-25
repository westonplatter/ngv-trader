"""add worker heartbeats table

Revision ID: e4f2a9b56c80
Revises: d2e13c7745ab
Create Date: 2026-02-19 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f2a9b56c80"
down_revision: Union[str, Sequence[str], None] = "d2e13c7745ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("worker_type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("worker_type", name="uq_worker_heartbeats_worker_type"),
    )
    op.create_index(
        "ix_worker_heartbeats_worker_type_heartbeat_at",
        "worker_heartbeats",
        ["worker_type", "heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_heartbeats_worker_type_heartbeat_at",
        table_name="worker_heartbeats",
    )
    op.drop_table("worker_heartbeats")
