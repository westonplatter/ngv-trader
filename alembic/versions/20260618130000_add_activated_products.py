"""add activated_products table and seed core products

Revision ID: a1c3e5g7i9k1
Revises: 19412730c878
Create Date: 2026-06-18 13:00:00.000000

"""

from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c3e5g7i9k1"
down_revision: Union[str, Sequence[str], None] = "19412730c878"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed products: exchange is intentionally left NULL so it gets discovered from
# IBKR on first sync. months_ahead defaults to 12.
_SEED_SYMBOLS = ["CL", "NG", "ZB", "ZN", "ES", "NQ"]


def upgrade() -> None:
    op.create_table(
        "activated_products",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("sec_type", sa.String(), nullable=False, server_default="FUT"),
        sa.Column("currency", sa.String(), nullable=False, server_default="USD"),
        sa.Column("months_ahead", sa.Integer(), nullable=False, server_default="12"),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("valid_exchanges", sa.String(), nullable=True),
        sa.Column("multiplier", sa.String(), nullable=True),
        sa.Column("trading_class", sa.String(), nullable=True),
        sa.Column("long_name", sa.String(), nullable=True),
        sa.Column("min_tick", sa.Float(), nullable=True),
        sa.Column("discovery_status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "sec_type", name="uq_activated_products_symbol_sec_type"),
    )

    activated_products = sa.table(
        "activated_products",
        sa.column("symbol", sa.String),
        sa.column("sec_type", sa.String),
        sa.column("currency", sa.String),
        sa.column("months_ahead", sa.Integer),
        sa.column("discovery_status", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        activated_products,
        [
            {
                "symbol": symbol,
                "sec_type": "FUT",
                "currency": "USD",
                "months_ahead": 12,
                "discovery_status": "pending",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for symbol in _SEED_SYMBOLS
        ],
    )


def downgrade() -> None:
    op.drop_table("activated_products")
