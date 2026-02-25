"""add contracts table

Revision ID: a1b2c3d4e5f6
Revises: f7a3c1d8e2b4
Create Date: 2026-02-20 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f7a3c1d8e2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contracts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("con_id", sa.Integer, nullable=False, unique=True),
        sa.Column("symbol", sa.String, nullable=False),
        sa.Column("sec_type", sa.String, nullable=False),
        sa.Column("exchange", sa.String, nullable=False),
        sa.Column("currency", sa.String, nullable=False),
        sa.Column("local_symbol", sa.String, nullable=True),
        sa.Column("trading_class", sa.String, nullable=True),
        sa.Column("contract_month", sa.String, nullable=True),
        sa.Column("contract_expiry", sa.String, nullable=True),
        sa.Column("multiplier", sa.String, nullable=True),
        sa.Column("strike", sa.Float, nullable=True),
        sa.Column("right", sa.String, nullable=True),
        sa.Column("primary_exchange", sa.String, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_contracts_fut_lookup",
        "contracts",
        ["symbol", "sec_type", "is_active", "contract_expiry"],
    )
    op.create_index(
        "ix_contracts_option_lookup",
        "contracts",
        ["symbol", "sec_type", "is_active", "strike", "right", "contract_expiry"],
    )


def downgrade() -> None:
    op.drop_index("ix_contracts_option_lookup", table_name="contracts")
    op.drop_index("ix_contracts_fut_lookup", table_name="contracts")
    op.drop_table("contracts")
