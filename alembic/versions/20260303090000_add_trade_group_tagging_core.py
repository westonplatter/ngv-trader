"""add trade-group tagging core tables

Revision ID: a1c2e3f4b5c6
Revises: f9b3d5e7a201
Create Date: 2026-03-03 09:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c2e3f4b5c6"
down_revision: Union[str, Sequence[str], None] = "f9b3d5e7a201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trade_groups",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_by", sa.Text(), nullable=True),
        sa.Column("closed_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'archived')", name="ck_trade_groups_status"
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trade_groups_account_created_at",
        "trade_groups",
        ["account_id", "created_at"],
    )

    op.create_table(
        "trade_group_executions",
        sa.Column("trade_group_id", sa.Integer(), nullable=False),
        sa.Column("trade_execution_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'rule', 'agent')",
            name="ck_trade_group_executions_source",
        ),
        sa.ForeignKeyConstraint(["trade_execution_id"], ["trade_executions.id"]),
        sa.ForeignKeyConstraint(["trade_group_id"], ["trade_groups.id"]),
        sa.PrimaryKeyConstraint("trade_group_id", "trade_execution_id"),
        sa.UniqueConstraint(
            "trade_execution_id", name="uq_trade_group_executions_trade_execution_id"
        ),
    )
    op.create_index(
        "ix_trade_group_executions_group_assigned_at",
        "trade_group_executions",
        ["trade_group_id", "assigned_at"],
    )

    op.create_table(
        "trade_group_execution_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trade_execution_id", sa.Integer(), nullable=False),
        sa.Column("from_trade_group_id", sa.Integer(), nullable=True),
        sa.Column("to_trade_group_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "event_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('assigned', 'reassigned', 'unassigned')",
            name="ck_trade_group_execution_events_type",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'rule', 'agent')",
            name="ck_trade_group_execution_events_source",
        ),
        sa.ForeignKeyConstraint(["from_trade_group_id"], ["trade_groups.id"]),
        sa.ForeignKeyConstraint(["to_trade_group_id"], ["trade_groups.id"]),
        sa.ForeignKeyConstraint(["trade_execution_id"], ["trade_executions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_trade_group_execution_events_execution_event_at",
        "trade_group_execution_events",
        ["trade_execution_id", "event_at"],
    )
    op.create_index(
        "ix_trade_group_execution_events_to_group_event_at",
        "trade_group_execution_events",
        ["to_trade_group_id", "event_at"],
    )

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tag_type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "tag_type IN ('theme', 'strategy', 'risk_intent', 'hedge_type', 'holding_horizon')",
            name="ck_tags_tag_type",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tag_type", "normalized_value", name="uq_tags_type_normalized_value"
        ),
    )
    op.create_index(
        "ix_tags_type_normalized_value", "tags", ["tag_type", "normalized_value"]
    )

    op.create_table(
        "tag_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("tag_type", sa.Text(), nullable=False),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entity_type IN ('orders', 'trades', 'trade_executions', 'trade_groups')",
            name="ck_tag_links_entity_type",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'rule', 'agent')", name="ck_tag_links_source"
        ),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type", "entity_id", "tag_id", name="uq_tag_links_entity_tag"
        ),
    )
    op.create_index("ix_tag_links_entity", "tag_links", ["entity_type", "entity_id"])
    op.create_index("ix_tag_links_tag_entity", "tag_links", ["tag_id", "entity_type"])
    op.create_index(
        "uq_tag_links_primary_strategy_trade_group",
        "tag_links",
        ["entity_id"],
        unique=True,
        postgresql_where=sa.text(
            "entity_type = 'trade_groups' AND tag_type = 'strategy' AND is_primary = true"
        ),
    )

    op.create_table(
        "trade_group_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_trade_group_id", sa.Integer(), nullable=False),
        sa.Column("child_trade_group_id", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "link_type IN ('roll_from', 'adjustment_of', 'child_campaign')",
            name="ck_trade_group_links_type",
        ),
        sa.CheckConstraint(
            "parent_trade_group_id <> child_trade_group_id",
            name="ck_trade_group_links_parent_child_different",
        ),
        sa.ForeignKeyConstraint(["child_trade_group_id"], ["trade_groups.id"]),
        sa.ForeignKeyConstraint(["parent_trade_group_id"], ["trade_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_trade_group_id",
            "child_trade_group_id",
            "link_type",
            name="uq_trade_group_links_parent_child_type",
        ),
    )
    op.create_index(
        "ix_trade_group_links_parent", "trade_group_links", ["parent_trade_group_id"]
    )
    op.create_index(
        "ix_trade_group_links_child", "trade_group_links", ["child_trade_group_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_trade_group_links_child", table_name="trade_group_links")
    op.drop_index("ix_trade_group_links_parent", table_name="trade_group_links")
    op.drop_table("trade_group_links")

    op.drop_index("uq_tag_links_primary_strategy_trade_group", table_name="tag_links")
    op.drop_index("ix_tag_links_tag_entity", table_name="tag_links")
    op.drop_index("ix_tag_links_entity", table_name="tag_links")
    op.drop_table("tag_links")

    op.drop_index("ix_tags_type_normalized_value", table_name="tags")
    op.drop_table("tags")

    op.drop_index(
        "ix_trade_group_execution_events_to_group_event_at",
        table_name="trade_group_execution_events",
    )
    op.drop_index(
        "ix_trade_group_execution_events_execution_event_at",
        table_name="trade_group_execution_events",
    )
    op.drop_table("trade_group_execution_events")

    op.drop_index(
        "ix_trade_group_executions_group_assigned_at",
        table_name="trade_group_executions",
    )
    op.drop_table("trade_group_executions")

    op.drop_index("ix_trade_groups_account_created_at", table_name="trade_groups")
    op.drop_table("trade_groups")
