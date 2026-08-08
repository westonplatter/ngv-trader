"""cleanup_orphaned_live_executions

Data migration: purge existing phantom "unsettled" ``live_executions`` rows whose
settled twin already exists in ``trade_executions`` under a DIFFERENT
``ib_exec_id`` — combo-leg id normalization (live id has an extra trailing leg
segment) and expiration/assignment/exercise book events (live synthetic fill vs a
``FLEX-TX-…`` row). The exact-id purge in ``intraday_sync_tws._purge_settled``
cannot see these, so they had accumulated (12 orphans at authoring time, oldest
weeks old) and one was double-counting realized P&L in the intraday overlay.

This clears the backlog immediately at deploy rather than waiting for the next
FlexQuery sync (which, once ``trade_sync_flexquery`` calls
``reconcile_orphaned_live_executions``, would also clear it). Any preemptive
trade-group tag on a purged live fill is carried onto its settled execution
first.

Unlike the frozen-logic backfill migrations, this calls the shipped
``reconcile_orphaned_live_executions`` directly: it is a one-time cleanup of
known rows (not an ongoing derivation), it runs exactly once, and on a fresh
database ``live_executions`` is empty so it is a harmless no-op. Live BAG
combo-summary orphans have no settled counterpart and are intentionally left in
place (see the module docstring).

Revision ID: 3f9a1c7d5e02
Revises: 4b2386b53758
Create Date: 2026-07-14 00:20:03.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from src.services.live_reconcile import reconcile_orphaned_live_executions

# revision identifiers, used by Alembic.
revision: str = "3f9a1c7d5e02"
down_revision: Union[str, Sequence[str], None] = "4b2386b53758"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    # Fresh database (e.g. the test DB): `live_executions` is empty, so the
    # reconcile below is a no-op by definition. Skip it — the shipped reconcile
    # reads `live_executions` columns added by LATER revisions, which do not
    # exist yet at this point in the chain.
    if bind.execute(sa.text("SELECT 1 FROM live_executions LIMIT 1")).first() is None:
        return

    session = Session(bind=bind)
    counts = reconcile_orphaned_live_executions(session)
    session.flush()
    print(
        f"[cleanup_orphaned_live_executions] leg_strip={counts['leg_strip']} "
        f"book_event={counts['book_event']} links_carried={counts['links_carried']} "
        f"unmatched={counts['unmatched']}"
    )


def downgrade() -> None:
    """No-op: the purged rows were redundant phantoms of settled executions and
    cannot be meaningfully reconstructed. The settled executions they duplicated
    remain intact."""
