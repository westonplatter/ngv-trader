"""add v_trade_realized_pnl read-only view

Revision ID: e7a1c9d4b2f8
Revises: c4f1a9b2d3e6
Create Date: 2026-06-26 13:00:00.000000

Creates a read-only view that exposes per-trade realized PnL computed from the
FlexQuery ``fifoPnlRealized`` field stored on each canonical execution's ``raw``
JSON. This is the analytics surface the OSI semantic model / tradebot
``query_metric`` tool sits on — no table columns, data migration, or backfill.

Realized-PnL rule (mirrors the on-read aggregation in ``trades.py``):
  - canonical executions only
  - ``SUM(fifoPnlRealized)`` — leg fills carry the realized PnL; synthetic
    ``combo_summary`` rows have no ``fifoPnlRealized`` and so contribute NULL,
    which ``SUM`` ignores. There is therefore no leg/combo double-counting.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c9d4b2f8"
down_revision: Union[str, Sequence[str], None] = "c4f1a9b2d3e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_VIEW_SQL = """
CREATE VIEW v_trade_realized_pnl AS
SELECT
    t.id               AS trade_id,
    t.account_id       AS account_id,
    t.symbol           AS symbol,
    t.sec_type         AS sec_type,
    t.status           AS status,
    t.last_executed_at AS last_executed_at,
    SUM((te.raw ->> 'fifoPnlRealized')::numeric)
        FILTER (WHERE te.is_canonical) AS realized_pnl
FROM trades t
LEFT JOIN trade_executions te ON te.trade_id = t.id
GROUP BY
    t.id,
    t.account_id,
    t.symbol,
    t.sec_type,
    t.status,
    t.last_executed_at
"""


def upgrade() -> None:
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_trade_realized_pnl")
