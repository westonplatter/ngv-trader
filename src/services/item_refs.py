"""Item references: the typed key that tags and tasks attach to, and how a
reference is validated and expanded.

Links attach to items by typed keys, not by row id where row ids are unstable
(docs/design/tags-and-tasks.md):

- ``trade`` / ``trade_group`` / ``task`` / ``strategy``: the row id.
- ``position``: ``(account_id, con_id)``. Sync replaces ``positions`` rows.
- ``live_execution``: the fill's ``ib_exec_id``, with ``account_id``/``con_id``
  denormalized. Order ids do not match across TWS and FlexQuery, so a live order's
  links are stored per fill and moved onto the settled ``trades`` row at settlement.

Writing links is ``item_links.py``; reading them back for display is
``item_descriptions.py``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import LiveExecution, Strategy, TagLink, Task, TaskLink, Trade, TradeGroup
from src.services.errors import NotFoundError, ServiceError

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


def live_order_key(live: LiveExecution) -> tuple[int, str, int] | None:
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
    key = live_order_key(live)
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
