"""Tasks API router: simple to-dos linked to strategies, groups, positions, and trades.

See docs/design/tags-and-tasks.md. A task's links survive the item closing
(a flat position stays linked) and are dropped only when the item is deleted.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.routers.tags import ItemRefBody, TagChip, resolve_items, resolve_tags, validate_created_by
from src.models import LiveExecution, LivePosition, Position, Tag, TagLink, Task, TaskLink, Trade
from src.services.item_links import (
    TASK_ENTITY_TYPES,
    ItemRef,
    attach_tag,
    attach_task,
    describe_items,
    detach_task,
    item_key,
    link_item,
    normalize_tag_value,
    now_utc,
    tags_by_item,
)

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

TASK_STATUSES = ("todo", "in_progress", "done")


class TaskLinkResponse(BaseModel):
    entity_type: str
    id: int | None = None
    account_id: int | None = None
    con_id: int | None = None
    ib_exec_id: str | None = None
    label: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_by: str


class TaskResponse(BaseModel):
    id: int
    title: str
    notes: str | None
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    links: list[TaskLinkResponse]
    tags: list[TagChip]


class TaskCreateRequest(BaseModel):
    title: str
    notes: str | None = None
    status: str = "todo"
    created_by: str = "user"
    links: list[ItemRefBody] = Field(default_factory=list)
    # Tag ids or names; names are created on first use.
    tags: list[int | str] = Field(default_factory=list)


class TaskPatchRequest(BaseModel):
    title: str | None = None
    notes: str | None = None
    status: str | None = None


class TaskLinksRequest(BaseModel):
    items: list[ItemRefBody] = Field(min_length=1)
    created_by: str = "user"


def _ensure_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _validate_status(status: str) -> str:
    if status not in TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {', '.join(TASK_STATUSES)}")
    return status


def _set_status(task: Task, status: str) -> None:
    task.status = _validate_status(status)
    task.completed_at = (task.completed_at or now_utc()) if status == "done" else None


def _responses(db: Session, tasks: list[Task]) -> list[TaskResponse]:
    task_ids = [task.id for task in tasks]
    links_by_task: dict[int, list[TaskLink]] = defaultdict(list)
    if task_ids:
        for link in db.execute(select(TaskLink).where(TaskLink.task_id.in_(task_ids)).order_by(TaskLink.created_at)).scalars():
            links_by_task[link.task_id].append(link)
    items_by_type: dict[str, list[Any]] = defaultdict(list)
    for links in links_by_task.values():
        for link in links:
            items_by_type[link.entity_type].append(item_key(link_item(link)))
    descriptions = {kind: describe_items(db, kind, keys) for kind, keys in items_by_type.items()}
    tags = tags_by_item(db, "task", task_ids)

    out = []
    for task in tasks:
        link_rows = []
        for link in links_by_task.get(task.id, []):
            item = link_item(link)
            details = dict(descriptions.get(link.entity_type, {}).get(item_key(item), {}))
            label = str(details.pop("label", item_key(item)))
            link_rows.append(
                TaskLinkResponse(
                    entity_type=link.entity_type,
                    id=item.id,
                    account_id=item.account_id,
                    con_id=item.con_id,
                    ib_exec_id=item.ib_exec_id,
                    label=label,
                    details=details,
                    created_by=link.created_by,
                )
            )
        out.append(
            TaskResponse(
                id=task.id,
                title=task.title,
                notes=task.notes,
                status=task.status,
                created_by=task.created_by,
                created_at=task.created_at,
                updated_at=task.updated_at,
                completed_at=task.completed_at,
                links=link_rows,
                tags=[TagChip(**chip) for chip in tags.get(task.id, [])],
            )
        )
    return out


def _symbol_task_ids(db: Session, symbol: str):
    """Tasks linked to a trade, live fill, or position on this symbol."""
    upper = symbol.upper()
    position_keys = select(Position.account_id, Position.con_id).where(func.upper(Position.symbol) == upper)
    live_position_keys = select(LivePosition.account_id, LivePosition.con_id).where(func.upper(LivePosition.symbol) == upper)
    return select(TaskLink.task_id).where(
        or_(
            TaskLink.trade_id.in_(select(Trade.id).where(func.upper(Trade.symbol) == upper)),
            TaskLink.ib_exec_id.in_(select(LiveExecution.ib_exec_id).where(func.upper(LiveExecution.symbol) == upper)),
            tuple_(TaskLink.account_id, TaskLink.con_id).in_(position_keys),
            tuple_(TaskLink.account_id, TaskLink.con_id).in_(live_position_keys),
        )
    )


@router.get("/tasks", response_model=list[TaskResponse])
def list_tasks(  # noqa: PLR0913
    status: str | None = Query(default=None),
    include_done: bool = Query(default=False),
    tag: str | None = Query(default=None),
    strategy_id: int | None = Query(default=None),
    trade_group_id: int | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Tasks, newest first. Done tasks are left out unless ``include_done`` or ``status=done``."""
    stmt = select(Task)
    if status is not None:
        stmt = stmt.where(Task.status == _validate_status(status))
    elif not include_done:
        stmt = stmt.where(Task.status != "done")
    if tag:
        stmt = stmt.where(
            Task.id.in_(
                select(TagLink.task_id)
                .join(Tag, Tag.id == TagLink.tag_id)
                .where(TagLink.entity_type == "task", TagLink.ended_at.is_(None), Tag.normalized_value == normalize_tag_value(tag))
            )
        )
    if strategy_id is not None:
        stmt = stmt.where(Task.id.in_(select(TaskLink.task_id).where(TaskLink.entity_type == "strategy", TaskLink.strategy_id == strategy_id)))
    if trade_group_id is not None:
        stmt = stmt.where(Task.id.in_(select(TaskLink.task_id).where(TaskLink.entity_type == "trade_group", TaskLink.trade_group_id == trade_group_id)))
    if symbol:
        stmt = stmt.where(Task.id.in_(_symbol_task_ids(db, symbol)))
    tasks = list(db.execute(stmt.order_by(Task.created_at.desc(), Task.id.desc()).limit(limit)).scalars())
    return _responses(db, tasks)


@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(body: TaskCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    created_by = validate_created_by(body.created_by)
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title cannot be empty")
    items = resolve_items(db, body.links, TASK_ENTITY_TYPES) if body.links else []
    # Resolve tags before writing anything: an unknown id is a 404, not an FK error at commit.
    tags = resolve_tags(db, body.tags, created_by, create=True) if body.tags else []
    now = now_utc()
    task = Task(title=title, notes=body.notes or None, status="todo", created_by=created_by, created_at=now, updated_at=now)
    _set_status(task, body.status)
    db.add(task)
    db.flush()
    for item in items:
        attach_task(db, task.id, item, created_by)
    for tag in tags:
        attach_tag(db, tag.id, ItemRef("task", id=task.id), created_by)
    db.commit()
    return _responses(db, [task])[0]


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = DB_SESSION_DEPENDENCY):
    return _responses(db, [_ensure_task(db, task_id)])[0]


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
def patch_task(task_id: int, body: TaskPatchRequest, db: Session = DB_SESSION_DEPENDENCY):
    task = _ensure_task(db, task_id)
    if body.title is not None:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="title cannot be empty")
        task.title = body.title.strip()
    if "notes" in body.model_fields_set:
        task.notes = body.notes or None
    if body.status is not None:
        _set_status(task, body.status)
    task.updated_at = now_utc()
    db.commit()
    return _responses(db, [task])[0]


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY):
    db.delete(_ensure_task(db, task_id))
    db.commit()
    response.status_code = 204
    return response


@router.post("/tasks/{task_id}/links", response_model=TaskResponse, status_code=201)
def link_task(task_id: int, body: TaskLinksRequest, db: Session = DB_SESSION_DEPENDENCY):
    """Link items to a task. A live fill fans out to every live fill of its order."""
    task = _ensure_task(db, task_id)
    created_by = validate_created_by(body.created_by)
    for item in resolve_items(db, body.items, TASK_ENTITY_TYPES):
        attach_task(db, task.id, item, created_by)
        db.flush()
    task.updated_at = now_utc()
    db.commit()
    return _responses(db, [task])[0]


@router.delete("/tasks/{task_id}/links", response_model=TaskResponse)
def unlink_task(task_id: int, body: TaskLinksRequest, db: Session = DB_SESSION_DEPENDENCY):
    task = _ensure_task(db, task_id)
    for item in _unlink_items(db, body.items):
        detach_task(db, task.id, item)
    task.updated_at = now_utc()
    db.commit()
    return _responses(db, [task])[0]


def _unlink_items(db: Session, items: list[ItemRefBody]) -> list[ItemRef]:
    """Like ``resolve_items``, but a deleted item can still be unlinked by its key."""
    out = []
    for body in items:
        ref = body.ref()
        if ref.entity_type == "live_execution" and db.execute(select(LiveExecution.id).where(LiveExecution.ib_exec_id == ref.ib_exec_id)).first():
            out += resolve_items(db, [body], TASK_ENTITY_TYPES)
        else:
            out.append(ref)
    return out

