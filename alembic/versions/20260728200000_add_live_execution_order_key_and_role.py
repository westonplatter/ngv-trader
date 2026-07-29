"""add order grouping key + exec_role to live_executions

Fix C / U3 of docs/plans/2026-07-08-001-feat-unsettled-tws-contract-parity-plan.md.

The intraday feed delivers a combo order as one BAG summary fill plus one fill
per leg, but ``live_executions`` stored no key tying them together and no role,
so the Trades table rendered an unsettled spread as N unrelated rows. These
columns carry the broker's order identity (``permId``, falling back to
``orderId``) and the resolved COMBO/LEG role.

Additive and nullable/defaulted; no backfill. Live rows are short-lived (purged
by ``_purge_settled`` as they settle) so the next intraday sync repopulates them.

Revision ID: 7c31ab90f4d2
Revises: 2bc294c04f36
Create Date: 2026-07-28 20:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c31ab90f4d2"
down_revision: Union[str, Sequence[str], None] = "2bc294c04f36"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("live_executions", sa.Column("ib_perm_id", sa.Integer(), nullable=True))
    op.add_column("live_executions", sa.Column("ib_order_id", sa.Integer(), nullable=True))
    op.add_column(
        "live_executions",
        sa.Column("exec_role", sa.Text(), nullable=False, server_default="standalone"),
    )
    op.create_index("ix_live_executions_ib_perm_id", "live_executions", ["ib_perm_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_live_executions_ib_perm_id", table_name="live_executions")
    op.drop_column("live_executions", "exec_role")
    op.drop_column("live_executions", "ib_order_id")
    op.drop_column("live_executions", "ib_perm_id")
