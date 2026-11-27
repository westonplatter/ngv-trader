"""order legs

Adds `order_legs` for the legs of a combo (BAG) order and widens `orders.quantity` to
a float, since TWS reports fractional and raw quantities. Adds `orders.remaining_quantity`
and `orders.exec_role` (`combo_summary` or `standalone`).

Raw op calls only, so the migration does not depend on live service code.

Revision ID: e1a7c9d4b608
Revises: c5d8a1e3f702
Create Date: 2026-11-27 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a7c9d4b608"
down_revision: Union[str, Sequence[str], None] = "c5d8a1e3f702"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("orders", "quantity", existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)
    op.add_column("orders", sa.Column("remaining_quantity", sa.Float(), nullable=True))
    op.add_column("orders", sa.Column("exec_role", sa.String(), nullable=False, server_default="standalone"))
    op.execute("UPDATE orders SET remaining_quantity = GREATEST(quantity - filled_quantity, 0)")
    op.create_table(
        "order_legs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("leg_index", sa.Integer(), nullable=False),
        sa.Column("con_id", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("open_close", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("sec_type", sa.String(), nullable=True),
        sa.Column("local_symbol", sa.String(), nullable=True),
        sa.Column("strike", sa.Float(), nullable=True),
        sa.Column("right", sa.String(), nullable=True),
        sa.Column("contract_expiry", sa.String(), nullable=True),
        sa.UniqueConstraint("order_id", "leg_index", name="uq_order_legs_order_id_leg_index"),
    )


def downgrade() -> None:
    op.drop_table("order_legs")
    op.drop_column("orders", "exec_role")
    op.drop_column("orders", "remaining_quantity")
    op.alter_column("orders", "quantity", existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False, postgresql_using="round(quantity)::integer")
