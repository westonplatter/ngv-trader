"""Tag and task links: attach, detach, and the sync hooks that keep links
attached to the right item as fills settle and positions close.

Item keys and validation are ``item_refs.py``. The sync hooks here are called
from the settle paths in ``src/services/group_link_carryover.py`` and from the
position syncs.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import LiveExecution, LivePosition, Position, TagLink, TaskLink, TradeExecution
from src.services.intraday_overlay import ct_date
from src.services.item_refs import ItemRef, link_filter, link_item, live_order_key


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_tag_link(tag_id: int, item: ItemRef, created_by: str, assigned_at: datetime | None = None, ended_at: datetime | None = None) -> TagLink:
    """The one place a ``tag_links`` row is built from an item reference."""
    return TagLink(tag_id=tag_id, entity_type=item.entity_type, created_by=created_by, assigned_at=assigned_at or now_utc(), ended_at=ended_at, **item.key())


def attach_tag(session: Session, tag_id: int, item: ItemRef, created_by: str) -> bool:
    """Open a tag link unless one is already open. Returns whether a row was added."""
    exists = session.execute(select(TagLink.id).where(TagLink.tag_id == tag_id, TagLink.ended_at.is_(None), *link_filter(TagLink, item))).first()
    if exists:
        return False
    session.add(new_tag_link(tag_id, item, created_by))
    return True


def move_tag_links(session: Session, source_tag_id: int, target_tag_id: int) -> int:
    """Re-point every link of one tag at another (a merge). Returns the links moved.

    An open link becomes an open link on the target unless the item already has
    one; an ended link is copied with its dates, so history survives the merge.
    The source's rows are deleted; deleting the source tag itself is the caller's.
    """
    moved = 0
    for link in session.execute(select(TagLink).where(TagLink.tag_id == source_tag_id)).scalars().all():
        item = link_item(link)
        if link.ended_at is None:
            moved += attach_tag(session, target_tag_id, item, link.created_by)
        else:
            session.add(new_tag_link(target_tag_id, item, link.created_by, assigned_at=link.assigned_at, ended_at=link.ended_at))
            moved += 1
        session.delete(link)
        session.flush()
    return moved


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
        key = live_order_key(live)
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


def end_flat_position_tags(session: Session, now: datetime | None = None, snapshot_as_of: dict[int, date] | None = None) -> int:
    """Soft-end open position tags whose contract is flat in both settled and live data.

    Never keyed off a row delete: the FlexQuery position sync drops contracts that
    are missing from yesterday's report, including positions opened today. So a
    tag only ends once the account's settled snapshot is dated on or after the day
    the tag was applied — otherwise its absence proves nothing.

    ``snapshot_as_of`` supplies the snapshot date for accounts that have no
    ``positions`` rows left to read it from (an account that went flat).
    """
    now = now or now_utc()
    held = open_position_keys(session)
    snapshot_dates = dict(session.execute(select(Position.account_id, func.max(Position.as_of_date)).group_by(Position.account_id)).all())
    snapshot_dates.update(snapshot_as_of or {})
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
