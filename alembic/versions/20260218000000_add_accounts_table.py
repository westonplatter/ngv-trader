"""add accounts table

Revision ID: b7d1e2f3a4c5
Revises: a6c9b6424a2f
Create Date: 2026-02-18 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d1e2f3a4c5"
down_revision: Union[str, Sequence[str], None] = "a6c9b6424a2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create accounts table
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("account", sa.String, nullable=False, unique=True),
        sa.Column("alias", sa.String, nullable=True),
    )

    # 2. Insert distinct account values from positions into accounts
    op.execute("INSERT INTO accounts (account) " "SELECT DISTINCT account FROM positions WHERE account IS NOT NULL")

    # 3. Add account_id column to positions (nullable initially)
    op.add_column("positions", sa.Column("account_id", sa.Integer, nullable=True))

    # 4. Backfill account_id from accounts table
    op.execute("UPDATE positions SET account_id = accounts.id " "FROM accounts WHERE positions.account = accounts.account")

    # 5. Make account_id NOT NULL
    op.alter_column("positions", "account_id", nullable=False)

    # 6. Drop old unique constraint and account column
    op.drop_constraint("uq_account_con_id", "positions", type_="unique")
    op.drop_column("positions", "account")

    # 7. Add new unique constraint on (account_id, con_id)
    op.create_unique_constraint("uq_account_id_con_id", "positions", ["account_id", "con_id"])


def downgrade() -> None:
    # Reverse: restore account column, backfill from accounts, drop account_id
    op.drop_constraint("uq_account_id_con_id", "positions", type_="unique")

    op.add_column("positions", sa.Column("account", sa.String, nullable=True))

    op.execute("UPDATE positions SET account = accounts.account " "FROM accounts WHERE positions.account_id = accounts.id")

    op.alter_column("positions", "account", nullable=False)
    op.drop_column("positions", "account_id")

    op.create_unique_constraint("uq_account_con_id", "positions", ["account", "con_id"])

    op.drop_table("accounts")
