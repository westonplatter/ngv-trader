"""add trades and trade_executions tables

Revision ID: d5f1a3b7c901
Revises: a6c51b7d2f44
Create Date: 2026-02-27 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5f1a3b7c901"
down_revision: Union[str, Sequence[str], None] = "a6c51b7d2f44"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ib_perm_id", sa.Integer(), nullable=True),
        sa.Column("order_ref", sa.Text(), nullable=True),
        sa.Column("ib_order_id", sa.Integer(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("sec_type", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=True),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("total_quantity", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_price", sa.Float(), nullable=True),
        sa.Column("first_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Partial unique: one trade per (account, ib_perm_id) when perm_id is meaningful
    op.create_index(
        "ix_trades_account_perm_id",
        "trades",
        ["account_id", "ib_perm_id"],
        unique=True,
        postgresql_where=sa.text("ib_perm_id > 0"),
    )
    # Non-unique lookup index on order_ref (order_ref is NOT unique — IBKR
    # tools like SpreadTrader reuse the same ref across many trades).
    op.create_index(
        "ix_trades_account_order_ref",
        "trades",
        ["account_id", "order_ref"],
        unique=False,
        postgresql_where=sa.text("order_ref IS NOT NULL"),
    )
    # Lookup by account + recency
    op.create_index(
        "ix_trades_account_last_exec",
        "trades",
        ["account_id", sa.text("last_executed_at DESC")],
    )

    op.create_table(
        "trade_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ib_exec_id", sa.Text(), nullable=False),
        sa.Column("exec_id_base", sa.Text(), nullable=False),
        sa.Column("exec_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ib_perm_id", sa.Integer(), nullable=True),
        sa.Column("ib_order_id", sa.Integer(), nullable=True),
        sa.Column("order_ref", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("side", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("liquidity", sa.Text(), nullable=True),
        sa.Column("commission", sa.Float(), nullable=True),
        sa.Column("is_canonical", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("raw", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Primary idempotency key
    op.create_index(
        "ix_trade_executions_ib_exec_id",
        "trade_executions",
        ["ib_exec_id"],
        unique=True,
    )
    # Correction revision lookup
    op.create_index(
        "ix_trade_executions_base_rev",
        "trade_executions",
        ["account_id", "exec_id_base", sa.text("exec_revision DESC")],
    )
    # Execution timeline per trade
    op.create_index(
        "ix_trade_executions_trade_time",
        "trade_executions",
        ["trade_id", "executed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_trade_executions_trade_time", table_name="trade_executions")
    op.drop_index("ix_trade_executions_base_rev", table_name="trade_executions")
    op.drop_index("ix_trade_executions_ib_exec_id", table_name="trade_executions")
    op.drop_table("trade_executions")

    op.drop_index("ix_trades_account_last_exec", table_name="trades")
    op.drop_index("ix_trades_account_order_ref", table_name="trades")
    op.drop_index("ix_trades_account_perm_id", table_name="trades")
    op.drop_table("trades")
