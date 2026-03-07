"""simplify watch_list_instruments to join table

Revision ID: c3e5g7i9k1m3
Revises: b2d4f6a8c0e2
Create Date: 2026-03-07 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e5g7i9k1m3"
down_revision: Union[str, Sequence[str], None] = "b2d4f6a8c0e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the lookup index that references removed columns
    op.drop_index("ix_watch_list_instruments_lookup", table_name="watch_list_instruments")

    # Drop redundant columns (contract details now come from contracts table,
    # pricing comes from latest_futures / latest_futures_options)
    op.drop_column("watch_list_instruments", "symbol")
    op.drop_column("watch_list_instruments", "sec_type")
    op.drop_column("watch_list_instruments", "exchange")
    op.drop_column("watch_list_instruments", "currency")
    op.drop_column("watch_list_instruments", "local_symbol")
    op.drop_column("watch_list_instruments", "trading_class")
    op.drop_column("watch_list_instruments", "contract_month")
    op.drop_column("watch_list_instruments", "contract_expiry")
    op.drop_column("watch_list_instruments", "multiplier")
    op.drop_column("watch_list_instruments", "strike")
    op.drop_column("watch_list_instruments", "right")
    op.drop_column("watch_list_instruments", "primary_exchange")
    op.drop_column("watch_list_instruments", "bid_price")
    op.drop_column("watch_list_instruments", "ask_price")
    op.drop_column("watch_list_instruments", "close_price")
    op.drop_column("watch_list_instruments", "quote_as_of")

    # Remove orphaned rows whose con_id doesn't exist in contracts
    op.execute("DELETE FROM watch_list_instruments " "WHERE con_id NOT IN (SELECT con_id FROM contracts)")

    # Add foreign keys
    op.create_foreign_key(
        "fk_watch_list_instruments_watch_list_id",
        "watch_list_instruments",
        "watch_lists",
        ["watch_list_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_watch_list_instruments_con_id",
        "watch_list_instruments",
        "contracts",
        ["con_id"],
        ["con_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_watch_list_instruments_con_id", "watch_list_instruments", type_="foreignkey")
    op.drop_constraint("fk_watch_list_instruments_watch_list_id", "watch_list_instruments", type_="foreignkey")

    op.add_column("watch_list_instruments", sa.Column("symbol", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("sec_type", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("exchange", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("currency", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("local_symbol", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("trading_class", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("contract_month", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("contract_expiry", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("multiplier", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("strike", sa.Float(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("right", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("primary_exchange", sa.String(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("bid_price", sa.Float(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("ask_price", sa.Float(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("close_price", sa.Float(), nullable=True))
    op.add_column("watch_list_instruments", sa.Column("quote_as_of", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_watch_list_instruments_lookup",
        "watch_list_instruments",
        ["watch_list_id", "symbol", "sec_type"],
    )
