"""add last_trade_date to live_executions

Fix B / U2 of docs/plans/2026-07-08-001-feat-unsettled-tws-contract-parity-plan.md.

The intraday feed stored no expiry, so unsettled rows recovered one by inferring
it from ``local_symbol`` — exact for OCC-style equity options, but only
month-precise for futures options, whose local symbol carries no day. This
column persists IBKR's authoritative ``lastTradeDateOrContractMonth`` (stored
raw, "YYYYMMDD" or "YYYYMM"); the display layer prefers it over inference.

Additive and nullable; no backfill. Live rows are short-lived (purged by
``_purge_settled`` as they settle) so the next intraday sync repopulates them,
and existing rows keep rendering via local-symbol inference meanwhile.

Revision ID: 701c3434b8dc
Revises: 7c31ab90f4d2
Create Date: 2026-08-01 16:54:47.492892

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "701c3434b8dc"
down_revision: Union[str, Sequence[str], None] = "7c31ab90f4d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("live_executions", sa.Column("last_trade_date", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("live_executions", "last_trade_date")
