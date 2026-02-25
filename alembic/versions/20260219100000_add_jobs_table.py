"""add jobs table

Revision ID: d2e13c7745ab
Revises: c8f4d1e9a731
Create Date: 2026-02-19 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2e13c7745ab"
down_revision: Union[str, Sequence[str], None] = "c8f4d1e9a731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_type", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("result", sa.JSON, nullable=True),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("request_text", sa.Text, nullable=True),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_jobs_status_available_created",
        "jobs",
        ["status", "available_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_available_created", table_name="jobs")
    op.drop_table("jobs")
