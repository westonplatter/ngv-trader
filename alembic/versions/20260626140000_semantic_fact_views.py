"""replace realized-pnl view with base-grain + trade-grain fact views

Revision ID: f1b3d5a7c9e2
Revises: e7a1c9d4b2f8
Create Date: 2026-06-26 14:00:00.000000

Replaces the single pre-aggregated v_trade_realized_pnl view with two fact
sources for the semantic layer (see docs/core/semantic-queries.md):

  - v_execution_facts: one row per canonical execution (base grain). Additive
    measures (realized_pnl, commission) live here. realized_pnl is combo-safe
    (NULL on synthetic combo_summary rows, whose legs carry the PnL) and
    null-safe (NULLIF guards the JSON cast).
  - v_trade_facts: one row per trade (trade grain), for inherently trade-grain
    metrics (trade_count, win_rate). Rolls realized_pnl up from execution facts.

Both are read-only views over existing tables — no columns, data migration, or
backfill. Dimensions come from joins to conformed tables (accounts, contracts,
trade_groups) at query time, not from columns baked into a view.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b3d5a7c9e2"
down_revision: Union[str, Sequence[str], None] = "e7a1c9d4b2f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_EXECUTION_FACTS = """
CREATE VIEW v_execution_facts AS
SELECT
    te.id          AS execution_id,
    te.trade_id    AS trade_id,
    te.account_id  AS account_id,
    te.con_id      AS con_id,
    te.exec_role   AS exec_role,
    te.executed_at AS executed_at,
    te.quantity    AS quantity,
    te.price       AS price,
    te.commission  AS commission,
    CASE
        WHEN te.exec_role <> 'combo_summary'
        THEN NULLIF(te.raw ->> 'fifoPnlRealized', '')::numeric
    END AS realized_pnl
FROM trade_executions te
WHERE te.is_canonical
"""

_TRADE_FACTS = """
CREATE VIEW v_trade_facts AS
SELECT
    t.id               AS trade_id,
    t.account_id       AS account_id,
    t.symbol           AS symbol,
    t.sec_type         AS sec_type,
    t.side             AS side,
    t.status           AS status,
    t.last_executed_at AS last_executed_at,
    SUM(ef.realized_pnl) AS realized_pnl
FROM trades t
LEFT JOIN v_execution_facts ef ON ef.trade_id = t.id
GROUP BY t.id, t.account_id, t.symbol, t.sec_type, t.side, t.status, t.last_executed_at
"""

# Prior revision's view, recreated on downgrade.
_LEGACY_REALIZED_PNL = """
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
GROUP BY t.id, t.account_id, t.symbol, t.sec_type, t.status, t.last_executed_at
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_trade_realized_pnl")
    op.execute(_EXECUTION_FACTS)
    op.execute(_TRADE_FACTS)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_trade_facts")
    op.execute("DROP VIEW IF EXISTS v_execution_facts")
    op.execute(_LEGACY_REALIZED_PNL)
