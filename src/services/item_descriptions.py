"""Read-side lookups for tags and tasks: open tags per item, not-done task
counts per item, and a display label for an item of any entity type.

Keyed like the callers' rows are: an id, an ``ib_exec_id``, or
``(account_id, con_id)`` (see ``item_refs.item_key``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from src.models import LiveExecution, LivePosition, Position, Strategy, Tag, TagLink, Task, TaskLink, Trade, TradeGroup
from src.services.item_links import open_position_keys
from src.services.item_refs import ENTITY_KEYS


def _key_of(row: Any, entity_type: str) -> Any:
    cols = ENTITY_KEYS[entity_type]
    values = [getattr(row, col) for col in cols]
    return tuple(values) if len(values) > 1 else values[0]


def tag_chip(tag: Tag, link: TagLink) -> dict[str, Any]:
    return {
        "id": tag.id,
        "value": tag.value,
        "color": tag.color,
        "created_by": link.created_by,
        "assigned_at": link.assigned_at,
        "ended_at": link.ended_at,
    }


def tags_by_item(session: Session, entity_type: str, keys: Iterable[Any], include_ended: bool = False) -> dict[Any, list[dict[str, Any]]]:
    """Open tags per item, keyed like ``keys`` (an id, an ib_exec_id, or (account_id, con_id))."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    stmt = select(TagLink, Tag).join(Tag, Tag.id == TagLink.tag_id).where(TagLink.entity_type == entity_type)
    if not include_ended:
        stmt = stmt.where(TagLink.ended_at.is_(None))
    if entity_type == "position":
        stmt = stmt.where(tuple_(TagLink.account_id, TagLink.con_id).in_(keys))
    else:
        stmt = stmt.where(getattr(TagLink, ENTITY_KEYS[entity_type][0]).in_(keys))
    out: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for link, tag in session.execute(stmt.order_by(Tag.normalized_value)).all():
        out[_key_of(link, entity_type)].append(tag_chip(tag, link))
    return out


def open_task_counts(session: Session, entity_type: str, keys: Iterable[Any]) -> dict[Any, int]:
    """Count of not-done tasks linked to each item."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    cols = [getattr(TaskLink, col) for col in ENTITY_KEYS[entity_type]]
    stmt = (
        select(*cols, func.count(func.distinct(TaskLink.task_id)))
        .join(Task, Task.id == TaskLink.task_id)
        .where(TaskLink.entity_type == entity_type, Task.status != "done")
        .group_by(*cols)
    )
    if entity_type == "position":
        stmt = stmt.where(tuple_(TaskLink.account_id, TaskLink.con_id).in_(keys))
    else:
        stmt = stmt.where(cols[0].in_(keys))
    out: dict[Any, int] = {}
    for row in session.execute(stmt).all():
        *key, count = row
        out[tuple(key) if len(key) > 1 else key[0]] = count
    return out


def _qty(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{abs(value):g}"


# ---------------------------------------------------------------------------
# Item descriptions: one describer per entity type
# ---------------------------------------------------------------------------

Description = dict[str, Any]
Describer = Callable[[Session, list[Any]], dict[Any, Description]]


def _label(*parts: Any) -> str:
    return " ".join(str(part) for part in parts if part)


def _describe_trades(session: Session, keys: list[Any]) -> dict[Any, Description]:
    return {
        trade.id: {
            "label": _label(trade.side, _qty(trade.total_quantity), trade.symbol),
            "symbol": trade.symbol,
            "account_id": trade.account_id,
            "executed_at": trade.last_executed_at,
        }
        for trade in session.execute(select(Trade).where(Trade.id.in_(keys))).scalars()
    }


def _describe_live_executions(session: Session, keys: list[Any]) -> dict[Any, Description]:
    return {
        live.ib_exec_id: {
            "label": _label(live.side, _qty(live.quantity), live.local_symbol or live.symbol),
            "symbol": live.symbol,
            "account_id": live.account_id,
            "executed_at": live.exec_time,
            "settled": False,
        }
        for live in session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.in_(keys))).scalars()
    }


def _describe_positions(session: Session, keys: list[Any]) -> dict[Any, Description]:
    """Live row first, else the settled one; a key held nowhere still gets a label."""
    held = open_position_keys(session)
    settled = {(p.account_id, p.con_id): p for p in session.execute(select(Position).where(tuple_(Position.account_id, Position.con_id).in_(keys))).scalars()}
    live = {
        (p.account_id, p.con_id): p
        for p in session.execute(select(LivePosition).where(tuple_(LivePosition.account_id, LivePosition.con_id).in_(keys))).scalars()
    }
    out: dict[Any, Description] = {}
    for key in keys:
        row: Any = live.get(key) or settled.get(key)
        out[key] = {
            "label": (row.local_symbol or row.symbol) if row is not None else f"con_id {key[1]}",
            "symbol": row.symbol if row is not None else None,
            "account_id": key[0],
            "quantity": row.position if row is not None else 0.0,
            "open": key in held,
        }
    return out


def _describe_trade_groups(session: Session, keys: list[Any]) -> dict[Any, Description]:
    rows = session.execute(select(TradeGroup, Strategy.name).outerjoin(Strategy, Strategy.id == TradeGroup.strategy_id).where(TradeGroup.id.in_(keys))).all()
    return {group.id: {"label": group.name, "status": group.status, "strategy": strategy_name} for group, strategy_name in rows}


def _describe_strategies(session: Session, keys: list[Any]) -> dict[Any, Description]:
    return {strategy.id: {"label": strategy.name} for strategy in session.execute(select(Strategy).where(Strategy.id.in_(keys))).scalars()}


def _describe_tasks(session: Session, keys: list[Any]) -> dict[Any, Description]:
    return {task.id: {"label": task.title, "status": task.status} for task in session.execute(select(Task).where(Task.id.in_(keys))).scalars()}


# Adding an entity type: add its key columns to ENTITY_KEYS and a describer here.
DESCRIBERS: dict[str, Describer] = {
    "trade": _describe_trades,
    "live_execution": _describe_live_executions,
    "position": _describe_positions,
    "trade_group": _describe_trade_groups,
    "strategy": _describe_strategies,
    "task": _describe_tasks,
}
assert set(DESCRIBERS) == set(ENTITY_KEYS), "every entity type needs a describer"


def describe_items(session: Session, entity_type: str, keys: Iterable[Any]) -> dict[Any, Description]:
    """A display label plus a few fields for each item, keyed like ``keys``."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    return DESCRIBERS[entity_type](session, keys)
