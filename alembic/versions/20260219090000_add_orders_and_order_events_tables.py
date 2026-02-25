"""add orders and order events tables

Revision ID: c8f4d1e9a731
Revises: b7d1e2f3a4c5
Create Date: 2026-02-19 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f4d1e9a731"
down_revision: Union[str, Sequence[str], None] = "b7d1e2f3a4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer, nullable=False),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("sec_type", sa.String, nullable=False),
        sa.Column("exchange", sa.String, nullable=False),
        sa.Column("currency", sa.String, nullable=False),
        sa.Column("side", sa.String, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("order_type", sa.String, nullable=False),
        sa.Column("tif", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("con_id", sa.Integer, nullable=True),
        sa.Column("local_symbol", sa.String, nullable=True),
        sa.Column("trading_class", sa.String, nullable=True),
        sa.Column("contract_month", sa.String, nullable=True),
        sa.Column("contract_expiry", sa.String, nullable=True),
        sa.Column("ib_order_id", sa.Integer, nullable=True),
        sa.Column("ib_perm_id", sa.Integer, nullable=True),
        sa.Column("filled_quantity", sa.Float, nullable=False, server_default="0"),
        sa.Column("avg_fill_price", sa.Float, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("request_text", sa.Text, nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_index("ix_orders_status_created_at", "orders", ["status", "created_at"])

    op.create_table(
        "order_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("status", sa.String, nullable=True),
        sa.Column("filled_quantity", sa.Float, nullable=True),
        sa.Column("avg_fill_price", sa.Float, nullable=True),
        sa.Column("ib_order_id", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_order_events_order_id_created_at",
        "order_events",
        ["order_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_events_order_id_created_at", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_orders_status_created_at", table_name="orders")
    op.drop_table("orders")
