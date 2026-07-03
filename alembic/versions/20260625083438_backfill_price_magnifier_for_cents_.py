"""backfill price_magnifier for cents-quoted contracts

Revision ID: d58cc2d31128
Revises: 299393aba4a0
Create Date: 2026-06-25 08:34:38.467181

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d58cc2d31128"
down_revision: Union[str, Sequence[str], None] = "299393aba4a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Futures roots quoted in CENTS (per bushel / per lb) on CME/CBOT — their
# market-data price is 100x the dollar unit that multiplier/avgCost expect, so
# priceMagnifier = 100. Verified against CME contract specs (price quotation =
# "cents per <unit>"). Frozen here as a one-time seed for rows synced before the
# column existed; IBKR's ContractDetails.priceMagnifier overwrites this on the
# next contract sync. Everything else (index futures, $-quoted energy/metals,
# Treasury points, equities/options) is magnifier 1.
CENTS_QUOTED_ROOTS = (
    "ZC",  # corn
    "ZW",  # Chicago SRW wheat
    "KE",  # KC HRW wheat
    "ZS",  # soybeans
    "ZL",  # soybean oil (cents/lb)
    "ZO",  # oats
    "HE",  # lean hogs (cents/lb)
    "LE",  # live cattle (cents/lb)
    "GF",  # feeder cattle (cents/lb)
)


def upgrade() -> None:
    """Backfill price_magnifier for existing rows where it is still NULL.

    Only touches NULL rows so any value already captured from IBKR is preserved.
    Matches on ``symbol`` (the root, shared by a product's FUT and FOP rows).
    """
    bind = op.get_bind()
    # Cents-quoted roots → 100.
    bind.execute(
        sa.text("UPDATE contracts SET price_magnifier = 100 " "WHERE price_magnifier IS NULL AND symbol = ANY(:roots)"),
        {"roots": list(CENTS_QUOTED_ROOTS)},
    )
    # Everything else still NULL → 1 (the safe default).
    bind.execute(sa.text("UPDATE contracts SET price_magnifier = 1 WHERE price_magnifier IS NULL"))


def downgrade() -> None:
    """Data-only backfill; nothing to structurally reverse.

    (The column itself is dropped by the preceding migration's downgrade.)
    """
    pass
