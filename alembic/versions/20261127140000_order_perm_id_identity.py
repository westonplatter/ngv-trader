"""order perm id identity

`ib_perm_id` becomes the unique broker identity of an order. TWS reports permId 0
while it has not acknowledged an order, so 0 means "unknown" and is stored as NULL.

- `orders.ib_perm_id` and `live_executions.ib_perm_id` widen to BIGINT, like `trades`.
- permId 0 becomes NULL on both tables.
- Duplicate non-NULL permIds on `orders` are resolved: the newest row by
  `updated_at` (highest `id` on a tie) keeps the permId, the others get NULL.
- Partial unique index `uq_orders_ib_perm_id` on `orders.ib_perm_id` where not NULL.
- `orders.ib_client_id` records the API client that placed or last reported an order.

Raw SQL only, so the migration does not depend on live service code.

Downgrade drops the index and column and narrows the types. It does not restore
permId 0 or the permIds cleared by the dedup.

Revision ID: 9b4c2e7a1d35
Revises: 3f0fedd368ff
Create Date: 2026-11-27 14:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b4c2e7a1d35"
down_revision: Union[str, Sequence[str], None] = "3f0fedd368ff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE orders SET ib_perm_id = NULL WHERE ib_perm_id = 0")
    op.execute("UPDATE live_executions SET ib_perm_id = NULL WHERE ib_perm_id = 0")
    op.execute("""
        UPDATE orders AS o
        SET ib_perm_id = NULL
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY ib_perm_id ORDER BY updated_at DESC, id DESC) AS rn
            FROM orders
            WHERE ib_perm_id IS NOT NULL
        ) AS ranked
        WHERE o.id = ranked.id AND ranked.rn > 1
        """)
    op.alter_column("orders", "ib_perm_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)
    op.alter_column("live_executions", "ib_perm_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)
    op.add_column("orders", sa.Column("ib_client_id", sa.Integer(), nullable=True))
    op.create_index(
        "uq_orders_ib_perm_id",
        "orders",
        ["ib_perm_id"],
        unique=True,
        postgresql_where=sa.text("ib_perm_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_orders_ib_perm_id", table_name="orders", postgresql_where=sa.text("ib_perm_id IS NOT NULL"))
    op.drop_column("orders", "ib_client_id")
    op.alter_column("live_executions", "ib_perm_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True)
    op.alter_column("orders", "ib_perm_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True)
