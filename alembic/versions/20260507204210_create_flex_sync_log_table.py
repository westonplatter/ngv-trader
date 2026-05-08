"""create flex_sync_log table

Revision ID: 01ca3f6d2394
Revises: 6b5e1576ec39
Create Date: 2026-05-07 20:42:10.293960

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01ca3f6d2394"
down_revision: Union[str, Sequence[str], None] = "6b5e1576ec39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "flex_sync_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Integer(),
            sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'success', 'error', 'partial')",
            name="ck_flex_sync_log_status",
        ),
    )
    op.create_index(
        "ix_flex_sync_log_account_range",
        "flex_sync_log",
        ["account_id", "start_date", "end_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_flex_sync_log_account_range", table_name="flex_sync_log")
    op.drop_table("flex_sync_log")
