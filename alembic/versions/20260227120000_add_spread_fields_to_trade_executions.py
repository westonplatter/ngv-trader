"""add sec_type, con_id, exec_role to trade_executions

Revision ID: e8a2c4d6f103
Revises: d5f1a3b7c901
Create Date: 2026-02-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8a2c4d6f103"
down_revision: Union[str, Sequence[str], None] = "d5f1a3b7c901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- trade_executions: new columns ---
    op.add_column("trade_executions", sa.Column("sec_type", sa.Text(), nullable=True))
    op.add_column("trade_executions", sa.Column("con_id", sa.Integer(), nullable=True))
    op.add_column(
        "trade_executions",
        sa.Column("exec_role", sa.Text(), nullable=False, server_default="standalone"),
    )

    # Partial index: fast combo-summary lookups
    op.create_index(
        "ix_trade_executions_sec_type",
        "trade_executions",
        ["sec_type"],
        postgresql_where=sa.text("sec_type IS NOT NULL"),
    )
    # Role-based filtering
    op.create_index(
        "ix_trade_executions_exec_role",
        "trade_executions",
        ["exec_role"],
        postgresql_where=sa.text("exec_role != 'standalone'"),
    )

    # --- Backfill existing rows from raw JSON ---
    # Extract sec_type from raw->'contract'->>'secType'
    op.execute(sa.text("""
            UPDATE trade_executions
            SET sec_type = raw->'contract'->>'secType'
            WHERE raw->'contract'->>'secType' IS NOT NULL
              AND sec_type IS NULL
        """))
    # Extract con_id from raw->'contract'->>'conId'
    op.execute(sa.text("""
            UPDATE trade_executions
            SET con_id = (raw->'contract'->>'conId')::int
            WHERE raw->'contract'->>'conId' IS NOT NULL
              AND con_id IS NULL
        """))
    # Tag combo summary fills (secType = BAG)
    op.execute(sa.text("""
            UPDATE trade_executions
            SET exec_role = 'combo_summary'
            WHERE sec_type = 'BAG'
        """))
    # Tag leg fills: non-BAG executions whose parent trade also has a BAG execution
    op.execute(sa.text("""
            UPDATE trade_executions te
            SET exec_role = 'leg'
            WHERE te.sec_type IS NOT NULL
              AND te.sec_type != 'BAG'
              AND te.exec_role = 'standalone'
              AND EXISTS (
                  SELECT 1 FROM trade_executions sibling
                  WHERE sibling.trade_id = te.trade_id
                    AND sibling.sec_type = 'BAG'
              )
        """))
    # Backfill trades.sec_type = 'BAG' for parent trades that have combo fills
    op.execute(sa.text("""
            UPDATE trades t
            SET sec_type = 'BAG'
            WHERE EXISTS (
                SELECT 1 FROM trade_executions te
                WHERE te.trade_id = t.id
                  AND te.sec_type = 'BAG'
            )
            AND (t.sec_type IS NULL OR t.sec_type != 'BAG')
        """))


def downgrade() -> None:
    op.drop_index("ix_trade_executions_exec_role", table_name="trade_executions")
    op.drop_index("ix_trade_executions_sec_type", table_name="trade_executions")
    op.drop_column("trade_executions", "exec_role")
    op.drop_column("trade_executions", "con_id")
    op.drop_column("trade_executions", "sec_type")
