"""Item references: the typed key that tags and tasks attach to, and how a
reference is validated and expanded.

Links attach to items by typed keys, not by row id where row ids are unstable
(docs/design/tags-and-tasks.md):

- ``trade`` / ``trade_group`` / ``task`` / ``strategy``: the row id.
- ``position``: ``(account_id, con_id)``. Sync replaces ``positions`` rows.
- ``live_execution``: the fill's ``ib_exec_id``, with ``account_id``/``con_id``
  denormalized. Order ids do not match across TWS and FlexQuery, so a live order's
  links are stored per fill and moved onto the settled ``trades`` row at settlement.

``ENTITY_SPECS`` is the one table of what differs per entity type (key columns,
how a reference is validated, how it fans out); everything here looks the type up
there instead of switching on it. Adding an entity type is one ``EntitySpec``
here plus a describer in ``item_descriptions.py``.

Writing links is ``item_links.py``; reading them back for display is
``item_descriptions.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from src.domain.enums import EntityType
from src.models import LiveExecution, Strategy, TagLink, Task, TaskLink, Trade, TradeGroup
from src.services.errors import NotFoundError, ServiceError

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
        return spec_for(self.entity_type).link_columns(self)


def _require(condition: bool, message: str, error: type[ItemError] = ItemError) -> None:
    if not condition:
        raise error(message)


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


# ---------------------------------------------------------------------------
# Entity-type registry
# ---------------------------------------------------------------------------

Resolver = Callable[[Session, ItemRef], ItemRef]
Expander = Callable[[Session, ItemRef], list[ItemRef]]


def _resolve_position(session: Session, ref: ItemRef) -> ItemRef:
    _require(ref.account_id is not None and ref.con_id is not None, "a position needs account_id and con_id")
    return ItemRef(EntityType.POSITION, account_id=ref.account_id, con_id=ref.con_id)


def _resolve_live_execution(session: Session, ref: ItemRef) -> ItemRef:
    _require(bool(ref.ib_exec_id), "a live_execution needs ib_exec_id")
    live = session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id == ref.ib_exec_id)).scalar_one_or_none()
    _require(live is not None, f"live execution {ref.ib_exec_id} not found", ItemNotFound)
    assert live is not None
    return ItemRef(EntityType.LIVE_EXECUTION, account_id=live.account_id, con_id=live.con_id, ib_exec_id=live.ib_exec_id)


def _resolver_for_row_id(model: type[Any]) -> Resolver:
    """A resolver for an entity keyed by the row id of ``model``."""

    def resolve(session: Session, ref: ItemRef) -> ItemRef:
        _require(ref.id is not None, f"a {ref.entity_type} needs id")
        _require(session.get(model, ref.id) is not None, f"{ref.entity_type} {ref.id} not found", ItemNotFound)
        return ItemRef(ref.entity_type, id=ref.id)

    return resolve


def _expand_to_self(session: Session, item: ItemRef) -> list[ItemRef]:
    return [item]


def _expand_live_execution(session: Session, item: ItemRef) -> list[ItemRef]:
    """A live fill stands for every live fill of its order."""
    assert item.ib_exec_id is not None
    return [
        ItemRef(EntityType.LIVE_EXECUTION, account_id=live.account_id, con_id=live.con_id, ib_exec_id=live.ib_exec_id)
        for live in live_order_fills(session, item.ib_exec_id)
    ]


@dataclass(frozen=True)
class EntitySpec:
    """Everything that differs between entity types for item links.

    ``key_columns`` are the link-row columns that identify the item and
    ``ref_fields`` the ``ItemRef`` attributes that hold the same values, in the
    same order (a row-id entity keeps its id in ``ItemRef.id``).
    ``denormalized`` columns are copied onto a link row but never matched on.
    ``resolve`` validates a reference and fills the denormalized fields;
    ``expand`` fans one resolved reference out to the items it stands for.
    """

    entity_type: EntityType
    key_columns: tuple[str, ...]
    ref_fields: tuple[str, ...]
    resolve: Resolver
    expand: Expander
    denormalized: tuple[str, ...] = ()

    @staticmethod
    def _collapse(values: Sequence[Any]) -> Any:
        """A one-column key is the bare value; a composite key is a tuple."""
        return tuple(values) if len(values) > 1 else values[0]

    def key_of(self, item: ItemRef) -> Any:
        """The lookup key ``describe_items`` / ``tags_by_item`` use for an item."""
        return self._collapse([getattr(item, field) for field in self.ref_fields])

    def row_key(self, row: Any) -> Any:
        """The same lookup key, read off a link row."""
        return self._collapse([getattr(row, column) for column in self.key_columns])

    def link_columns(self, item: ItemRef) -> dict[str, Any]:
        """The typed key columns (plus denormalized ones) for a link row."""
        columns = {column: getattr(item, field) for column, field in zip(self.key_columns, self.ref_fields, strict=True)}
        columns.update({column: getattr(item, column) for column in self.denormalized})
        return columns

    def filter_clauses(self, model: LinkModel, item: ItemRef) -> list[Any]:
        """WHERE clauses matching this item's key columns on ``model``."""
        return [getattr(model, column) == getattr(item, field) for column, field in zip(self.key_columns, self.ref_fields, strict=True)]

    def key_in(self, model: LinkModel, keys: Sequence[Any]) -> Any:
        """A WHERE clause matching any of ``keys`` (shaped like ``key_of``) on ``model``."""
        columns = [getattr(model, column) for column in self.key_columns]
        return tuple_(*columns).in_(keys) if len(columns) > 1 else columns[0].in_(keys)

    def item_of(self, link: TagLink | TaskLink) -> ItemRef:
        """The item a link row points at."""
        fields = {field: getattr(link, column) for column, field in zip(self.key_columns, self.ref_fields, strict=True)}
        fields.update({column: getattr(link, column) for column in self.denormalized})
        return ItemRef(self.entity_type, **fields)


def _row_id_spec(entity_type: EntityType, column: str, model: type[Any]) -> EntitySpec:
    return EntitySpec(entity_type, (column,), ("id",), _resolver_for_row_id(model), _expand_to_self)


ENTITY_SPECS: dict[EntityType, EntitySpec] = {
    spec.entity_type: spec
    for spec in (
        _row_id_spec(EntityType.TRADE, "trade_id", Trade),
        _row_id_spec(EntityType.TRADE_GROUP, "trade_group_id", TradeGroup),
        _row_id_spec(EntityType.TASK, "task_id", Task),
        _row_id_spec(EntityType.STRATEGY, "strategy_id", Strategy),
        # A position is (account_id, con_id), never a row id: sync replaces those rows.
        EntitySpec(EntityType.POSITION, ("account_id", "con_id"), ("account_id", "con_id"), _resolve_position, _expand_to_self),
        # A live fill carries account_id/con_id too, so the settle path can find its position.
        EntitySpec(
            EntityType.LIVE_EXECUTION,
            ("ib_exec_id",),
            ("ib_exec_id",),
            _resolve_live_execution,
            _expand_live_execution,
            denormalized=("account_id", "con_id"),
        ),
    )
}
assert set(ENTITY_SPECS) == set(EntityType), "every entity type needs an EntitySpec"


def spec_for(entity_type: str) -> EntitySpec:
    """The spec for a stored or requested entity-type string; ``KeyError`` if unknown."""
    return ENTITY_SPECS[cast(EntityType, entity_type)]


def resolve_item(session: Session, ref: ItemRef, allowed: Iterable[str]) -> ItemRef:
    """Validate a reference and fill denormalized fields; raises ``ItemError`` / ``ItemNotFound``."""
    _require(ref.entity_type in allowed, f"entity_type must be one of {', '.join(allowed)}")
    return spec_for(ref.entity_type).resolve(session, ref)


def expand_items(session: Session, refs: Iterable[ItemRef], allowed: Iterable[str]) -> list[ItemRef]:
    """Resolve refs, fanning a live fill out to every live fill of its order. Deduped."""
    allowed = tuple(allowed)
    out: dict[tuple, ItemRef] = {}
    for ref in refs:
        resolved = resolve_item(session, ref, allowed)
        spec = spec_for(resolved.entity_type)
        for item in spec.expand(session, resolved):
            out[(item.entity_type, spec.key_of(item))] = item
    return list(out.values())


def link_filter(model: LinkModel, item: ItemRef) -> list[Any]:
    """WHERE clauses matching one item's links on ``model``."""
    return [model.entity_type == item.entity_type, *spec_for(item.entity_type).filter_clauses(model, item)]


def item_key(item: ItemRef) -> Any:
    """The lookup key ``describe_items`` / ``tags_by_item`` use for an item."""
    return spec_for(item.entity_type).key_of(item)


def link_item(link: TagLink | TaskLink) -> ItemRef:
    """The item a link row points at."""
    return spec_for(link.entity_type).item_of(link)
