"""add security data tables and underlying_con_id

Revision ID: b2d4f6a8c0e2
Revises: a1c2e3f4b5c6
Create Date: 2026-03-06 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2d4f6a8c0e2"
down_revision: Union[str, Sequence[str], None] = "a1c2e3f4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add underlying_con_id to contracts
    op.add_column("contracts", sa.Column("underlying_con_id", sa.Integer(), nullable=True))

    # latest_futures
    op.create_table(
        "latest_futures",
        sa.Column("con_id", sa.Integer(), sa.ForeignKey("contracts.con_id"), primary_key=True),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ts_futures
    op.create_table(
        "ts_futures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("con_id", sa.Integer(), sa.ForeignKey("contracts.con_id"), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ts_futures_con_id_market_ts", "ts_futures", ["con_id", "market_ts"])
    op.create_index("ix_ts_futures_market_ts", "ts_futures", ["market_ts"])

    # latest_futures_options
    op.create_table(
        "latest_futures_options",
        sa.Column("con_id", sa.Integer(), sa.ForeignKey("contracts.con_id"), primary_key=True),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("iv", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("gamma", sa.Float(), nullable=True),
        sa.Column("theta", sa.Float(), nullable=True),
        sa.Column("vega", sa.Float(), nullable=True),
        sa.Column("und_price", sa.Float(), nullable=True),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ts_futures_options
    op.create_table(
        "ts_futures_options",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("con_id", sa.Integer(), sa.ForeignKey("contracts.con_id"), nullable=False),
        sa.Column("bid", sa.Float(), nullable=True),
        sa.Column("ask", sa.Float(), nullable=True),
        sa.Column("last", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("iv", sa.Float(), nullable=True),
        sa.Column("delta", sa.Float(), nullable=True),
        sa.Column("gamma", sa.Float(), nullable=True),
        sa.Column("theta", sa.Float(), nullable=True),
        sa.Column("vega", sa.Float(), nullable=True),
        sa.Column("und_price", sa.Float(), nullable=True),
        sa.Column("market_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ts_futures_options_con_id_market_ts", "ts_futures_options", ["con_id", "market_ts"])
    op.create_index("ix_ts_futures_options_market_ts", "ts_futures_options", ["market_ts"])


def downgrade() -> None:
    op.drop_table("ts_futures_options")
    op.drop_table("latest_futures_options")
    op.drop_table("ts_futures")
    op.drop_table("latest_futures")
    op.drop_column("contracts", "underlying_con_id")
