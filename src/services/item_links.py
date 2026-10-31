"""Free-form tags and task links: item references, live-order fan-out, and sync hooks.

Tags (``tag_links``) and tasks (``task_links``) attach to items by typed keys, not
by row id where row ids are unstable (docs/design/tags-and-tasks.md):

- ``trade`` / ``trade_group`` / ``task`` / ``strategy``: the row id.
- ``position``: ``(account_id, con_id)``. Sync replaces ``positions`` rows.
- ``live_execution``: the fill's ``ib_exec_id``, with ``account_id``/``con_id``
  denormalized. Order ids do not match across TWS and FlexQuery, so a live order's
  links are stored per fill and moved onto the settled ``trades`` row at settlement.

The sync hooks here are called from the settle paths in
``src/services/group_link_carryover.py`` and from the position syncs.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from src.models import (
    LiveExecution,
    LivePosition,
    Position,
    Strategy,
    Tag,
    TagLink,
    Task,
    TaskLink,
    Trade,
    TradeExecution,
    TradeGroup,
)
from src.services.errors import NotFoundError, ServiceError
from src.services.intraday_overlay import ct_date

# Typed key columns per entity type. A live fill also carries account_id/con_id.
ENTITY_KEYS: dict[str, tuple[str, ...]] = {
    "trade": ("trade_id",),
    "trade_group": ("trade_group_id",),
    "task": ("task_id",),
    "strategy": ("strategy_id",),
    "position": ("account_id", "con_id"),
    "live_execution": ("ib_exec_id",),
}
LinkModel = type[TagLink] | type[TaskLink]


class ItemError(ServiceError):
    """An item reference that is malformed."""


class ItemNotFound(ItemError, NotFoundError):
    """A well-formed item reference that names a missing item."""


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def normalize_tag_value(value: str) -> str:
    """Fold case, spaces, ``-`` and ``_``: "Long Beta", "long_beta", "long-beta" match."""
    return re.sub(r"[\s_\-]+", "-", value.strip().lower()).strip("-")


@dataclass(frozen=True)
class ItemRef:
    """One taggable or linkable item, by its typed key."""

    entity_type: str
    id: int | None = None
    account_id: int | None = None
    con_id: int | None = None
    ib_exec_id: str | None = None

    def key(self) -> dict[str, Any]:
        """The typed key columns for a link row."""
        if self.entity_type == "position":
            return {"account_id": self.account_id, "con_id": self.con_id}
        if self.entity_type == "live_execution":
            return {"ib_exec_id": self.ib_exec_id, "account_id": self.account_id, "con_id": self.con_id}
        return {ENTITY_KEYS[self.entity_type][0]: self.id}


def _require(condition: bool, message: str, error: type[ItemError] = ItemError) -> None:
    if not condition:
        raise error(message)


def resolve_item(session: Session, ref: ItemRef, allowed: Iterable[str]) -> ItemRef:
    """Validate a reference and fill denormalized fields; raises ``ItemError`` / ``ItemNotFound``."""
    _require(ref.entity_type in allowed, f"entity_type must be one of {', '.join(allowed)}")
    if ref.entity_type == "position":
        _require(ref.account_id is not None and ref.con_id is not None, "a position needs account_id and con_id")
        return ItemRef("position", account_id=ref.account_id, con_id=ref.con_id)
    if ref.entity_type == "live_execution":
        _require(bool(ref.ib_exec_id), "a live_execution needs ib_exec_id")
        live = session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id == ref.ib_exec_id)).scalar_one_or_none()
        _require(live is not None, f"live execution {ref.ib_exec_id} not found", ItemNotFound)
        assert live is not None
        return ItemRef("live_execution", account_id=live.account_id, con_id=live.con_id, ib_exec_id=live.ib_exec_id)
    _require(ref.id is not None, f"a {ref.entity_type} needs id")
    model = {"trade": Trade, "trade_group": TradeGroup, "task": Task, "strategy": Strategy}[ref.entity_type]
    _require(session.get(model, ref.id) is not None, f"{ref.entity_type} {ref.id} not found", ItemNotFound)
    return ItemRef(ref.entity_type, id=ref.id)


def _order_key(live: LiveExecution) -> tuple[int, str, int] | None:
    """A live fill's order: ``permId`` when present, else ``orderId``, within its account."""
    if live.ib_perm_id:
        return (live.account_id, "perm", live.ib_perm_id)
    if live.ib_order_id:
        return (live.account_id, "order", live.ib_order_id)
    return None


def live_order_fills(session: Session, ib_exec_id: str) -> list[LiveExecution]:
    """Every live fill of the order this fill belongs to (a combo's summary and legs too)."""
    live = session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id == ib_exec_id)).scalar_one_or_none()
    if live is None:
        return []
    key = _order_key(live)
    if key is None:
        return [live]
    account_id, kind, value = key
    column = LiveExecution.ib_perm_id if kind == "perm" else LiveExecution.ib_order_id
    return list(session.execute(select(LiveExecution).where(LiveExecution.account_id == account_id, column == value)).scalars())


def expand_items(session: Session, refs: Iterable[ItemRef], allowed: Iterable[str]) -> list[ItemRef]:
    """Resolve refs, fanning a live fill out to every live fill of its order. Deduped."""
    allowed = tuple(allowed)
    out: dict[tuple, ItemRef] = {}
    for ref in refs:
        resolved = resolve_item(session, ref, allowed)
        if resolved.entity_type == "live_execution":
            assert resolved.ib_exec_id is not None
            for live in live_order_fills(session, resolved.ib_exec_id):
                item = ItemRef("live_execution", account_id=live.account_id, con_id=live.con_id, ib_exec_id=live.ib_exec_id)
                out[(item.entity_type, item.ib_exec_id)] = item
        else:
            out[(resolved.entity_type, resolved.id, resolved.account_id, resolved.con_id)] = resolved
    return list(out.values())


def link_filter(model: LinkModel, item: ItemRef) -> list[Any]:
    """WHERE clauses matching one item's links on ``model``."""
    clauses: list[Any] = [model.entity_type == item.entity_type]
    if item.entity_type == "position":
        clauses += [model.account_id == item.account_id, model.con_id == item.con_id]
    elif item.entity_type == "live_execution":
        clauses.append(model.ib_exec_id == item.ib_exec_id)
    else:
        clauses.append(getattr(model, ENTITY_KEYS[item.entity_type][0]) == item.id)
    return clauses


def attach_tag(session: Session, tag_id: int, item: ItemRef, created_by: str) -> bool:
    """Open a tag link unless one is already open. Returns whether a row was added."""
    exists = session.execute(select(TagLink.id).where(TagLink.tag_id == tag_id, TagLink.ended_at.is_(None), *link_filter(TagLink, item))).first()
    if exists:
        return False
    session.add(TagLink(tag_id=tag_id, entity_type=item.entity_type, created_by=created_by, assigned_at=now_utc(), **item.key()))
    return True


def detach_tag(session: Session, tag_id: int, item: ItemRef) -> int:
    """Remove a tag from an item by hand. Removes the open link only."""
    rows = session.execute(select(TagLink).where(TagLink.tag_id == tag_id, TagLink.ended_at.is_(None), *link_filter(TagLink, item))).scalars().all()
    for row in rows:
        session.delete(row)
    return len(rows)


def attach_task(session: Session, task_id: int, item: ItemRef, created_by: str) -> bool:
    exists = session.execute(select(TaskLink.id).where(TaskLink.task_id == task_id, *link_filter(TaskLink, item))).first()
    if exists:
        return False
    session.add(TaskLink(task_id=task_id, entity_type=item.entity_type, created_by=created_by, created_at=now_utc(), **item.key()))
    return True


def detach_task(session: Session, task_id: int, item: ItemRef) -> int:
    rows = session.execute(select(TaskLink).where(TaskLink.task_id == task_id, *link_filter(TaskLink, item))).scalars().all()
    for row in rows:
        session.delete(row)
    return len(rows)


# ---------------------------------------------------------------------------
# Sync hooks
# ---------------------------------------------------------------------------


def carry_over_item_links(session: Session, live_ib_exec_id: str, trade_execution_ids: Iterable[int]) -> int:
    """Move a live fill's tag and task links onto the settled trade(s), then drop them.

    Each settled execution resolves to its parent ``trades`` row, so a trade
    collects the links of all its fills (duplicates are skipped). A combo summary
    passes several settled legs. Returns the number of links added.
    """
    execution_ids = list(dict.fromkeys(trade_execution_ids))
    tag_links = session.execute(select(TagLink).where(TagLink.entity_type == "live_execution", TagLink.ib_exec_id == live_ib_exec_id)).scalars().all()
    task_links = session.execute(select(TaskLink).where(TaskLink.entity_type == "live_execution", TaskLink.ib_exec_id == live_ib_exec_id)).scalars().all()
    if not tag_links and not task_links:
        return 0
    trade_ids = list(
        dict.fromkeys(session.execute(select(TradeExecution.trade_id).where(TradeExecution.id.in_(execution_ids))).scalars()) if execution_ids else []
    )
    if not trade_ids:
        return 0
    added = 0
    for trade_id in trade_ids:
        trade = ItemRef("trade", id=trade_id)
        for link in tag_links:
            if link.ended_at is None:
                added += attach_tag(session, link.tag_id, trade, link.created_by)
        for link in task_links:
            added += attach_task(session, link.task_id, trade, link.created_by)
        # Make the new rows visible to the duplicate check for the next fill.
        session.flush()
    for link in [*tag_links, *task_links]:
        session.delete(link)
    return added


def carry_over_settled_item_links(session: Session, settled_ids: set[str] | None = None) -> int:
    """The id-equality case: live links whose ``ib_exec_id`` has settled under the same id."""
    live_ids: set[str] = set()
    for model in (TagLink, TaskLink):
        stmt = select(model.ib_exec_id).where(model.entity_type == "live_execution")
        if settled_ids is not None:
            if not settled_ids:
                return 0
            stmt = stmt.where(model.ib_exec_id.in_(settled_ids))
        live_ids |= {value for value in session.execute(stmt).scalars() if value}
    if not live_ids:
        return 0
    settled = session.execute(select(TradeExecution.ib_exec_id, TradeExecution.id).where(TradeExecution.ib_exec_id.in_(live_ids))).all()
    return sum(carry_over_item_links(session, ib_exec_id, [execution_id]) for ib_exec_id, execution_id in settled)


def inherit_order_links(session: Session) -> int:  # noqa: C901, PLR0912
    """Give a late partial fill the tags and tasks already on its order's other live fills.

    Applies within one TWS order only (same ``permId``, else ``orderId``). Returns
    the number of links added.
    """
    lives = session.execute(select(LiveExecution)).scalars().all()
    by_order: dict[tuple, list[LiveExecution]] = defaultdict(list)
    for live in lives:
        key = _order_key(live)
        if key is not None:
            by_order[key].append(live)
    order_groups = [fills for fills in by_order.values() if len(fills) > 1]
    if not order_groups:
        return 0
    tags_by_exec: dict[str, dict[int, str]] = defaultdict(dict)
    for link in session.execute(select(TagLink).where(TagLink.entity_type == "live_execution", TagLink.ended_at.is_(None))).scalars():
        tags_by_exec[link.ib_exec_id or ""][link.tag_id] = link.created_by
    tasks_by_exec: dict[str, dict[int, str]] = defaultdict(dict)
    for link in session.execute(select(TaskLink).where(TaskLink.entity_type == "live_execution")).scalars():
        tasks_by_exec[link.ib_exec_id or ""][link.task_id] = link.created_by

    added = 0
    for fills in order_groups:
        order_tags: dict[int, str] = {}
        order_tasks: dict[int, str] = {}
        for live in fills:
            order_tags.update(tags_by_exec.get(live.ib_exec_id, {}))
            order_tasks.update(tasks_by_exec.get(live.ib_exec_id, {}))
        for live in fills:
            item = ItemRef("live_execution", account_id=live.account_id, con_id=live.con_id, ib_exec_id=live.ib_exec_id)
            for tag_id, created_by in order_tags.items():
                if tag_id not in tags_by_exec.get(live.ib_exec_id, {}):
                    added += attach_tag(session, tag_id, item, created_by)
            for task_id, created_by in order_tasks.items():
                if task_id not in tasks_by_exec.get(live.ib_exec_id, {}):
                    added += attach_task(session, task_id, item, created_by)
    return added


def open_position_keys(session: Session) -> set[tuple[int, int]]:
    """``(account_id, con_id)`` held in settled or live data, ignoring zero quantities."""
    settled = session.execute(select(Position.account_id, Position.con_id).where(Position.position != 0)).all()
    live = session.execute(select(LivePosition.account_id, LivePosition.con_id).where(LivePosition.position != 0)).all()
    return {(account_id, con_id) for account_id, con_id in [*settled, *live]}


def end_flat_position_tags(session: Session, now: datetime | None = None) -> int:
    """Soft-end open position tags whose contract is flat in both settled and live data.

    Never keyed off a row delete: the FlexQuery position sync drops contracts that
    are missing from yesterday's report, including positions opened today. So a
    tag only ends once the account's settled snapshot is dated on or after the day
    the tag was applied — otherwise its absence proves nothing.
    """
    now = now or now_utc()
    held = open_position_keys(session)
    snapshot_dates = dict(session.execute(select(Position.account_id, func.max(Position.as_of_date)).group_by(Position.account_id)).all())
    latest_any = session.execute(select(func.max(Position.as_of_date))).scalar_one_or_none()
    ended = 0
    links = session.execute(select(TagLink).where(TagLink.entity_type == "position", TagLink.ended_at.is_(None))).scalars().all()
    for link in links:
        if link.account_id is None or (link.account_id, link.con_id) in held:
            continue
        snapshot = snapshot_dates.get(link.account_id) or latest_any
        # as_of_date is a CT trading date; compare like with like.
        if snapshot is None or snapshot < ct_date(link.assigned_at):
            continue
        link.ended_at = now
        ended += 1
    return ended


# ---------------------------------------------------------------------------
# Read-side annotations
# ---------------------------------------------------------------------------


def _key_of(row: Any, entity_type: str) -> Any:
    cols = ENTITY_KEYS[entity_type]
    values = [getattr(row, col) for col in cols]
    return tuple(values) if len(values) > 1 else values[0]


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


def tag_chip(tag: Tag, link: TagLink) -> dict[str, Any]:
    return {
        "id": tag.id,
        "value": tag.value,
        "color": tag.color,
        "created_by": link.created_by,
        "assigned_at": link.assigned_at,
        "ended_at": link.ended_at,
    }


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


def describe_items(session: Session, entity_type: str, keys: Iterable[Any]) -> dict[Any, dict[str, Any]]:  # noqa: C901, PLR0912
    """A display label plus a few fields for each item, keyed like ``keys``."""
    keys = list(dict.fromkeys(keys))
    if not keys:
        return {}
    out: dict[Any, dict[str, Any]] = {}
    if entity_type == "trade":
        for trade in session.execute(select(Trade).where(Trade.id.in_(keys))).scalars():
            out[trade.id] = {
                "label": " ".join(str(part) for part in (trade.side, _qty(trade.total_quantity), trade.symbol) if part),
                "symbol": trade.symbol,
                "account_id": trade.account_id,
                "executed_at": trade.last_executed_at,
            }
    elif entity_type == "live_execution":
        for live in session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.in_(keys))).scalars():
            out[live.ib_exec_id] = {
                "label": " ".join(str(part) for part in (live.side, _qty(live.quantity), live.local_symbol or live.symbol) if part),
                "symbol": live.symbol,
                "account_id": live.account_id,
                "executed_at": live.exec_time,
                "settled": False,
            }
    elif entity_type == "position":
        held = open_position_keys(session)
        settled = {(p.account_id, p.con_id): p for p in session.execute(select(Position).where(tuple_(Position.account_id, Position.con_id).in_(keys))).scalars()}
        live = {
            (p.account_id, p.con_id): p for p in session.execute(select(LivePosition).where(tuple_(LivePosition.account_id, LivePosition.con_id).in_(keys))).scalars()
        }
        for key in keys:
            row: Any = live.get(key) or settled.get(key)
            out[key] = {
                "label": (row.local_symbol or row.symbol) if row is not None else f"con_id {key[1]}",
                "symbol": row.symbol if row is not None else None,
                "account_id": key[0],
                "quantity": row.position if row is not None else 0.0,
                "open": key in held,
            }
    elif entity_type == "trade_group":
        rows = session.execute(select(TradeGroup, Strategy.name).outerjoin(Strategy, Strategy.id == TradeGroup.strategy_id).where(TradeGroup.id.in_(keys))).all()
        for group, strategy_name in rows:
            out[group.id] = {"label": group.name, "status": group.status, "strategy": strategy_name}
    elif entity_type == "strategy":
        for strategy in session.execute(select(Strategy).where(Strategy.id.in_(keys))).scalars():
            out[strategy.id] = {"label": strategy.name}
    elif entity_type == "task":
        for task in session.execute(select(Task).where(Task.id.in_(keys))).scalars():
            out[task.id] = {"label": task.title, "status": task.status}
    return out


def _qty(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{abs(value):g}"


def item_key(item: ItemRef) -> Any:
    """The lookup key ``describe_items`` / ``tags_by_item`` use for an item."""
    if item.entity_type == "position":
        return (item.account_id, item.con_id)
    if item.entity_type == "live_execution":
        return item.ib_exec_id
    return item.id


def link_item(link: TagLink | TaskLink) -> ItemRef:
    """The item a link row points at."""
    if link.entity_type == "position":
        return ItemRef("position", account_id=link.account_id, con_id=link.con_id)
    if link.entity_type == "live_execution":
        return ItemRef("live_execution", account_id=link.account_id, con_id=link.con_id, ib_exec_id=link.ib_exec_id)
    return ItemRef(link.entity_type, id=getattr(link, ENTITY_KEYS[link.entity_type][0]))
