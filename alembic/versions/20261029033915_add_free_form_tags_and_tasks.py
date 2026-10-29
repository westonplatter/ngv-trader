"""add free-form tags and tasks

Repurposes `tags` / `tag_links` for free-form tags (docs/design/spec-tags-and-tasks.md)
and adds `tasks` / `task_links`. The previous migration emptied both tag tables,
so `tag_links` is dropped and recreated in its new shape rather than altered.

- `tags` loses `tag_type`; `normalized_value` becomes unique on its own; adds `color`.
- `tag_links` keys each item with typed columns (`trade_id`, `trade_group_id`,
  `task_id`, `account_id`+`con_id` for a position, `ib_exec_id` for a live fill),
  enforced by a per-type check constraint, and adds `ended_at`. One open link per
  (tag, item), via a partial unique index per entity type.
- `tasks` (title, notes, status) and `task_links`, which link a task to strategies,
  trade groups, positions, trades, and live fills the same way.

Downgrade restores the old empty shapes; free-form tags and tasks are lost.

Revision ID: 3f0fedd368ff
Revises: e68def4337bb
Create Date: 2026-10-29 03:39:15.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f0fedd368ff"
down_revision: Union[str, Sequence[str], None] = "e68def4337bb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAG_LINK_KEYS = {
    "trade": ("trade_id",),
    "trade_group": ("trade_group_id",),
    "task": ("task_id",),
    "position": ("account_id", "con_id"),
    "live_execution": ("ib_exec_id",),
}
TASK_LINK_KEYS = {
    "strategy": ("strategy_id",),
    "trade_group": ("trade_group_id",),
    "trade": ("trade_id",),
    "position": ("account_id", "con_id"),
    "live_execution": ("ib_exec_id",),
}


def _entity_key_check(keys: dict[str, tuple[str, ...]], id_columns: tuple[str, ...]) -> str:
    """Each entity type fills exactly its own key columns (a live fill also carries account_id)."""
    clauses = []
    for entity_type, required in keys.items():
        must = set(required) | ({"account_id"} if entity_type == "live_execution" else set())
        allowed_extra = {"con_id"} if entity_type == "live_execution" else set()
        parts = [f"entity_type = '{entity_type}'"]
        parts += [f"{col} IS NOT NULL" for col in sorted(must)]
        parts += [f"{col} IS NULL" for col in id_columns if col not in must and col not in allowed_extra]
        clauses.append("(" + " AND ".join(parts) + ")")
    return " OR ".join(clauses)


def _key_columns(*fk_columns: tuple[str, str]) -> list[sa.Column]:
    cols = [sa.Column(name, sa.Integer(), sa.ForeignKey(target, ondelete="CASCADE"), nullable=True) for name, target in fk_columns]
    return cols + [
        sa.Column("ib_exec_id", sa.Text(), nullable=True),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("con_id", sa.Integer(), nullable=True),
    ]


def _unique_indexes(table: str, owner: str, keys: dict[str, tuple[str, ...]], where_extra: str = "") -> None:
    for entity_type, cols in keys.items():
        op.create_index(
            f"uq_{table}_{entity_type}",
            table,
            [owner, *cols],
            unique=True,
            postgresql_where=sa.text(f"entity_type = '{entity_type}'{where_extra}"),
        )


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint("ck_tags_tag_type", "tags", type_="check")
    op.drop_index("ix_tags_type_normalized_value", table_name="tags")
    op.drop_constraint("uq_tags_type_normalized_value", "tags", type_="unique")
    op.drop_column("tags", "tag_type")
    op.add_column("tags", sa.Column("color", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_tags_normalized_value", "tags", ["normalized_value"])

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="todo"),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('todo', 'in_progress', 'done')", name="ck_tasks_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tasks_status_created_at", "tasks", ["status", "created_at"])

    op.drop_table("tag_links")
    tag_id_columns = ("trade_id", "trade_group_id", "task_id", "ib_exec_id", "account_id", "con_id")
    op.create_table(
        "tag_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        *_key_columns(("trade_id", "trades.id"), ("trade_group_id", "trade_groups.id"), ("task_id", "tasks.id")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_entity_key_check(TAG_LINK_KEYS, tag_id_columns), name="ck_tag_links_entity_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tag_links_tag_id", "tag_links", ["tag_id"])
    op.create_index("ix_tag_links_trade_id", "tag_links", ["trade_id"])
    op.create_index("ix_tag_links_trade_group_id", "tag_links", ["trade_group_id"])
    op.create_index("ix_tag_links_task_id", "tag_links", ["task_id"])
    op.create_index("ix_tag_links_account_con", "tag_links", ["account_id", "con_id"])
    op.create_index("ix_tag_links_ib_exec_id", "tag_links", ["ib_exec_id"])
    _unique_indexes("tag_links", "tag_id", TAG_LINK_KEYS, " AND ended_at IS NULL")

    task_id_columns = ("strategy_id", "trade_group_id", "trade_id", "ib_exec_id", "account_id", "con_id")
    op.create_table(
        "task_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        *_key_columns(("strategy_id", "strategies.id"), ("trade_group_id", "trade_groups.id"), ("trade_id", "trades.id")),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(_entity_key_check(TASK_LINK_KEYS, task_id_columns), name="ck_task_links_entity_key"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_links_task_id", "task_links", ["task_id"])
    op.create_index("ix_task_links_strategy_id", "task_links", ["strategy_id"])
    op.create_index("ix_task_links_trade_group_id", "task_links", ["trade_group_id"])
    op.create_index("ix_task_links_trade_id", "task_links", ["trade_id"])
    op.create_index("ix_task_links_account_con", "task_links", ["account_id", "con_id"])
    op.create_index("ix_task_links_ib_exec_id", "task_links", ["ib_exec_id"])
    _unique_indexes("task_links", "task_id", TASK_LINK_KEYS)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("task_links")
    op.drop_table("tag_links")
    op.drop_table("tasks")

    op.execute("DELETE FROM tags")
    op.drop_constraint("uq_tags_normalized_value", "tags", type_="unique")
    op.drop_column("tags", "color")
    op.add_column("tags", sa.Column("tag_type", sa.Text(), nullable=False))
    op.create_unique_constraint("uq_tags_type_normalized_value", "tags", ["tag_type", "normalized_value"])
    op.create_index("ix_tags_type_normalized_value", "tags", ["tag_type", "normalized_value"])
    op.create_check_constraint(
        "ck_tags_tag_type",
        "tags",
        "tag_type IN ('theme', 'strategy', 'risk_intent', 'hedge_type', 'holding_horizon')",
    )

    op.create_table(
        "tag_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("tag_type", sa.Text(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "entity_type IN ('orders', 'trades', 'trade_executions', 'trade_groups')",
            name="ck_tag_links_entity_type",
        ),
        sa.CheckConstraint("source IN ('manual', 'rule', 'agent')", name="ck_tag_links_source"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "tag_id", name="uq_tag_links_entity_tag"),
    )
    op.create_index("ix_tag_links_entity", "tag_links", ["entity_type", "entity_id"])
    op.create_index("ix_tag_links_tag_entity", "tag_links", ["tag_id", "entity_type"])
