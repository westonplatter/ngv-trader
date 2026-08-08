"""add flexquery token pause window

Adds a cooldown to `flexquery_tokens`. When IBKR answers `1025: Too many failed
attempts`, the token is paused for a window rather than being retried into a
deeper lockout; report fetches for it are held back until `paused_until` passes.
`pause_reason` records why, so the Accounts UI can explain the wait.

Additive and nullable — an existing token is simply never paused.

Revision ID: 349b5789b51c
Revises: 2b1bd1430647
Create Date: 2026-08-08 13:52:18.017647

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "349b5789b51c"
down_revision: Union[str, Sequence[str], None] = "2b1bd1430647"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("flexquery_tokens", sa.Column("paused_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("flexquery_tokens", sa.Column("pause_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("flexquery_tokens", "pause_reason")
    op.drop_column("flexquery_tokens", "paused_until")
