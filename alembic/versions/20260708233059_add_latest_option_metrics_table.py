"""add latest_option_metrics table

Revision ID: 01711d684634
Revises: 936d0e0f325f
Create Date: 2026-07-08 23:30:59.730916

Live greeks/IV for held option positions, written by the separate
``option_metrics.sync.tws`` job (decoupled from the real-time mark fetch that
writes ``latest_quote``). Keyed by ``con_id``, sec-type-agnostic (OPT/FOP), and
intentionally not FK'd to the futures-only ``contracts`` table — mirrors
``latest_quote``. Additive; no backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "01711d684634"
down_revision: Union[str, Sequence[str], None] = "936d0e0f325f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "latest_option_metrics",
        sa.Column("con_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("iv", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("gamma", sa.Float(), nullable=True),
        sa.Column("theta", sa.Float(), nullable=True),
        sa.Column("vega", sa.Float(), nullable=True),
        sa.Column("und_price", sa.Float(), nullable=True),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("con_id"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("latest_option_metrics")
