"""move strategies out of tags

Strategies were stored as `tags` rows with `tag_type = 'strategy'`, and a trade
group's strategy as its primary `tag_links` row. They become a first-class
`strategies` table and a `trade_groups.strategy_id` FK, freeing `tags` /
`tag_links` for free-form tags (docs/design/spec-tags-and-tasks.md).

Strategy ids are preserved, so existing deep links still resolve. Only the
primary strategy link of each group is carried over — the UI never wrote any
other kind. Every row in `tags` / `tag_links` is then deleted: besides
strategies, the catalog only ever held the never-used `theme`, `risk_intent`,
`hedge_type`, and `holding_horizon` types, which are dropped rather than migrated.

Downgrade rebuilds the strategy tags and primary links from `strategies` and
`trade_groups.strategy_id`. Rows of the dropped types are not restored.

Revision ID: e68def4337bb
Revises: 349b5789b51c
Create Date: 2026-10-29 03:28:52.929857

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e68def4337bb"
down_revision: Union[str, Sequence[str], None] = "349b5789b51c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PRIMARY_STRATEGY_WHERE = "entity_type = 'trade_groups' AND tag_type = 'strategy' AND is_primary = true"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", name="uq_strategies_normalized_name"),
    )
    op.execute(
        """
        INSERT INTO strategies (id, name, normalized_name, created_by, created_at, archived_at)
        SELECT id, value, normalized_value, created_by, created_at, archived_at
        FROM tags
        WHERE tag_type = 'strategy'
        """
    )
    op.execute("SELECT setval(pg_get_serial_sequence('strategies', 'id'), COALESCE((SELECT MAX(id) FROM strategies), 0) + 1, false)")

    op.add_column("trade_groups", sa.Column("strategy_id", sa.Integer(), nullable=True))
    op.create_index("ix_trade_groups_strategy_id", "trade_groups", ["strategy_id"])
    op.create_foreign_key(
        "fk_trade_groups_strategy_id_strategies",
        "trade_groups",
        "strategies",
        ["strategy_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.execute(
        """
        UPDATE trade_groups AS tg
        SET strategy_id = tl.tag_id
        FROM tag_links AS tl
        WHERE tl.entity_type = 'trade_groups'
          AND tl.tag_type = 'strategy'
          AND tl.is_primary = true
          AND tl.entity_id = tg.id
        """
    )

    op.drop_index("uq_tag_links_primary_strategy_trade_group", table_name="tag_links")
    op.execute("DELETE FROM tag_links")
    op.execute("DELETE FROM tags")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        """
        INSERT INTO tags (id, tag_type, value, normalized_value, created_by, created_at, archived_at)
        SELECT id, 'strategy', name, normalized_name, created_by, created_at, archived_at
        FROM strategies
        """
    )
    op.execute("SELECT setval(pg_get_serial_sequence('tags', 'id'), COALESCE((SELECT MAX(id) FROM tags), 0) + 1, false)")
    op.execute(
        """
        INSERT INTO tag_links (entity_type, entity_id, tag_id, tag_type, is_primary, source, created_by)
        SELECT 'trade_groups', tg.id, tg.strategy_id, 'strategy', true, 'manual', s.created_by
        FROM trade_groups AS tg
        JOIN strategies AS s ON s.id = tg.strategy_id
        """
    )
    op.create_index(
        "uq_tag_links_primary_strategy_trade_group",
        "tag_links",
        ["entity_id"],
        unique=True,
        postgresql_where=sa.text(PRIMARY_STRATEGY_WHERE),
    )

    op.drop_constraint("fk_trade_groups_strategy_id_strategies", "trade_groups", type_="foreignkey")
    op.drop_index("ix_trade_groups_strategy_id", table_name="trade_groups")
    op.drop_column("trade_groups", "strategy_id")
    op.drop_table("strategies")
