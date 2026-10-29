"""Free-form tags API router: the tag catalog, attaching tags to items, and search by tag.

See docs/design/tags-and-tasks.md. Tags never group items and never feed
reporting; strategies and trade groups have their own routers.
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Tag, TagLink
from src.services.item_links import (
    TAG_ENTITY_TYPES,
    ItemError,
    ItemRef,
    attach_tag,
    describe_items,
    detach_tag,
    expand_items,
    item_key,
    link_item,
    normalize_tag_value,
    now_utc,
    tag_chip,
)

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

# `user`, or `agent:<name>` for writes made by an LLM agent.
CREATED_BY_PATTERN = re.compile(r"^(user|agent:[A-Za-z0-9_.\-]+)$")


def validate_created_by(created_by: str) -> str:
    if not CREATED_BY_PATTERN.match(created_by):
        raise HTTPException(status_code=400, detail="created_by must be 'user' or 'agent:<name>'")
    return created_by


class TagChip(BaseModel):
    """A tag as shown on an item, with who applied it there."""

    id: int
    value: str
    color: str | None
    created_by: str
    assigned_at: datetime
    ended_at: datetime | None = None


class TagResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    value: str
    normalized_value: str
    color: str | None
    created_by: str
    created_at: datetime
    archived_at: datetime | None
    # Open links per entity type, e.g. {"trade": 3, "position": 1}.
    usage: dict[str, int] = Field(default_factory=dict)


class TagCreateRequest(BaseModel):
    value: str
    color: str | None = None
    created_by: str = "user"


class TagPatchRequest(BaseModel):
    value: str | None = None
    color: str | None = None


class TagMergeRequest(BaseModel):
    into_tag_id: int


class ItemRefBody(BaseModel):
    """One item. ``id`` for trades, trade groups, tasks, and strategies; ``account_id`` +
    ``con_id`` for a position; ``ib_exec_id`` for a live (unsettled) fill."""

    entity_type: str
    id: int | None = None
    account_id: int | None = None
    con_id: int | None = None
    ib_exec_id: str | None = None

    def ref(self) -> ItemRef:
        return ItemRef(self.entity_type, id=self.id, account_id=self.account_id, con_id=self.con_id, ib_exec_id=self.ib_exec_id)


class TagLinksRequest(BaseModel):
    """Tags by id or by name; a name that does not exist yet is created when attaching."""

    tags: list[int | str] = Field(min_length=1)
    items: list[ItemRefBody] = Field(min_length=1)
    created_by: str = "user"


class TagLinksResponse(BaseModel):
    changed: int
    tags: list[TagResponse]


class TaggedItem(BaseModel):
    entity_type: str
    id: int | None = None
    account_id: int | None = None
    con_id: int | None = None
    ib_exec_id: str | None = None
    label: str
    details: dict[str, Any] = Field(default_factory=dict)
    tags: list[TagChip]


class TagSearchResponse(BaseModel):
    items: list[TaggedItem]


def _usage(db: Session, tag_ids: list[int]) -> dict[int, dict[str, int]]:
    if not tag_ids:
        return {}
    rows = db.execute(
        select(TagLink.tag_id, TagLink.entity_type, func.count())
        .where(TagLink.tag_id.in_(tag_ids), TagLink.ended_at.is_(None))
        .group_by(TagLink.tag_id, TagLink.entity_type)
    ).all()
    usage: dict[int, dict[str, int]] = defaultdict(dict)
    for tag_id, entity_type, count in rows:
        usage[tag_id][entity_type] = count
    return usage


def _responses(db: Session, tags: list[Tag]) -> list[TagResponse]:
    usage = _usage(db, [tag.id for tag in tags])
    out = []
    for tag in tags:
        response = TagResponse.model_validate(tag)
        response.usage = usage.get(tag.id, {})
        out.append(response)
    return out


def _ensure_tag(db: Session, tag_id: int) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


def get_or_create_tag(db: Session, value: str, created_by: str, color: str | None = None) -> Tag:
    """The tag with this normalized value, created if missing. Unarchives nothing."""
    normalized = normalize_tag_value(value)
    if not normalized:
        raise HTTPException(status_code=400, detail="value cannot be empty")
    existing = db.execute(select(Tag).where(Tag.normalized_value == normalized)).scalar_one_or_none()
    if existing is not None:
        return existing
    tag = Tag(value=value.strip(), normalized_value=normalized, color=color, created_by=created_by, created_at=now_utc())
    db.add(tag)
    db.flush()
    return tag


def _resolve_tags(db: Session, handles: list[int | str], created_by: str, create: bool) -> list[Tag]:
    tags: dict[int, Tag] = {}
    for handle in handles:
        if isinstance(handle, int):
            tag = _ensure_tag(db, handle)
        elif create:
            tag = get_or_create_tag(db, handle, created_by)
        else:
            found = db.execute(select(Tag).where(Tag.normalized_value == normalize_tag_value(handle))).scalar_one_or_none()
            if found is None:
                raise HTTPException(status_code=404, detail=f"Tag {handle!r} not found")
            tag = found
        tags[tag.id] = tag
    return list(tags.values())


def resolve_items(db: Session, items: list[ItemRefBody], allowed: tuple[str, ...]) -> list[ItemRef]:
    """Validate items and fan a live fill out to its whole order; 400/404 on bad input."""
    try:
        return expand_items(db, [item.ref() for item in items], allowed)
    except ItemError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


@router.get("/tags", response_model=list[TagResponse])
def list_tags(
    q: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(Tag)
    if not include_archived:
        stmt = stmt.where(Tag.archived_at.is_(None))
    if q:
        escaped = normalize_tag_value(q).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Tag.normalized_value.like(f"%{escaped}%", escape="\\"))
    tags = list(db.execute(stmt.order_by(Tag.normalized_value).limit(limit)).scalars())
    responses = _responses(db, tags)
    # Most-used first, so type-ahead suggests the tags actually in use.
    return sorted(responses, key=lambda tag: -sum(tag.usage.values()))


@router.post("/tags", response_model=TagResponse, status_code=201)
def create_tag(body: TagCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    tag = get_or_create_tag(db, body.value, validate_created_by(body.created_by), body.color)
    db.commit()
    return _responses(db, [tag])[0]


@router.patch("/tags/{tag_id}", response_model=TagResponse)
def patch_tag(tag_id: int, body: TagPatchRequest, db: Session = DB_SESSION_DEPENDENCY):
    tag = _ensure_tag(db, tag_id)
    if body.value is not None:
        normalized = normalize_tag_value(body.value)
        if not normalized:
            raise HTTPException(status_code=400, detail="value cannot be empty")
        duplicate = db.execute(select(Tag.id).where(Tag.normalized_value == normalized, Tag.id != tag_id)).first()
        if duplicate:
            raise HTTPException(status_code=409, detail="Another tag already has this name; merge instead")
        tag.value = body.value.strip()
        tag.normalized_value = normalized
    if "color" in body.model_fields_set:
        tag.color = body.color or None
    db.commit()
    return _responses(db, [tag])[0]


@router.post("/tags/{tag_id}/archive", response_model=TagResponse)
def archive_tag(tag_id: int, db: Session = DB_SESSION_DEPENDENCY):
    tag = _ensure_tag(db, tag_id)
    if tag.archived_at is None:
        tag.archived_at = now_utc()
        db.commit()
    return _responses(db, [tag])[0]


@router.post("/tags/{tag_id}/unarchive", response_model=TagResponse)
def unarchive_tag(tag_id: int, db: Session = DB_SESSION_DEPENDENCY):
    tag = _ensure_tag(db, tag_id)
    if tag.archived_at is not None:
        tag.archived_at = None
        db.commit()
    return _responses(db, [tag])[0]


@router.post("/tags/{tag_id}/merge", response_model=TagResponse)
def merge_tag(tag_id: int, body: TagMergeRequest, db: Session = DB_SESSION_DEPENDENCY):
    """Move every link of ``tag_id`` onto ``into_tag_id``, then delete ``tag_id``."""
    if body.into_tag_id == tag_id:
        raise HTTPException(status_code=400, detail="Cannot merge a tag into itself")
    source = _ensure_tag(db, tag_id)
    target = _ensure_tag(db, body.into_tag_id)
    for link in db.execute(select(TagLink).where(TagLink.tag_id == source.id)).scalars().all():
        if link.ended_at is None:
            attach_tag(db, target.id, link_item(link), link.created_by)
        else:
            db.add(
                TagLink(
                    tag_id=target.id,
                    entity_type=link.entity_type,
                    created_by=link.created_by,
                    assigned_at=link.assigned_at,
                    ended_at=link.ended_at,
                    **link_item(link).key(),
                )
            )
        db.flush()
    db.delete(source)
    db.commit()
    return _responses(db, [target])[0]


@router.post("/tag-links", response_model=TagLinksResponse, status_code=201)
def attach_tags(body: TagLinksRequest, db: Session = DB_SESSION_DEPENDENCY):
    """Attach tags to items. A live fill fans out to every live fill of its order."""
    created_by = validate_created_by(body.created_by)
    items = resolve_items(db, body.items, TAG_ENTITY_TYPES)
    tags = _resolve_tags(db, body.tags, created_by, create=True)
    changed = 0
    for tag in tags:
        for item in items:
            changed += attach_tag(db, tag.id, item, created_by)
            db.flush()
    db.commit()
    return TagLinksResponse(changed=changed, tags=_responses(db, tags))


@router.delete("/tag-links", response_model=TagLinksResponse)
def detach_tags(body: TagLinksRequest, db: Session = DB_SESSION_DEPENDENCY):
    """Remove tags from items by hand. A live fill fans out like attaching does."""
    items = resolve_items(db, body.items, TAG_ENTITY_TYPES)
    tags = _resolve_tags(db, body.tags, body.created_by, create=False)
    changed = sum(detach_tag(db, tag.id, item) for tag in tags for item in items)
    db.commit()
    return TagLinksResponse(changed=changed, tags=_responses(db, tags))


def _split(values: list[str] | None) -> set[str]:
    """Accept repeated params and comma lists alike: ?all=a&all=b or ?all=a,b."""
    out: set[str] = set()
    for value in values or []:
        out |= {normalize_tag_value(part) for part in value.split(",") if part.strip()}
    return out


@router.get("/tags/search", response_model=TagSearchResponse)
def search_by_tags(  # noqa: C901, PLR0912, PLR0913
    all_tags: list[str] | None = Query(default=None, alias="all"),
    any_tags: list[str] | None = Query(default=None, alias="any"),
    none_tags: list[str] | None = Query(default=None, alias="none"),
    entity_type: str | None = Query(default=None),
    include_ended: bool = Query(default=False),
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Items whose tags include every ``all``, at least one ``any``, and no ``none`` tag.

    With no ``all``/``any``, every tagged item matches (minus ``none``). Ended
    position tags are left out unless ``include_ended``.
    """
    if entity_type is not None and entity_type not in TAG_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail=f"entity_type must be one of {', '.join(TAG_ENTITY_TYPES)}")
    want_all, want_any, want_none = _split(all_tags), _split(any_tags), _split(none_tags)

    stmt = select(TagLink, Tag).join(Tag, Tag.id == TagLink.tag_id)
    if not include_ended:
        stmt = stmt.where(TagLink.ended_at.is_(None))
    if entity_type is not None:
        stmt = stmt.where(TagLink.entity_type == entity_type)
    by_item: dict[ItemRef, list[tuple[TagLink, Tag]]] = defaultdict(list)
    for link, tag in db.execute(stmt).all():
        item = link_item(link)
        if item.entity_type == "live_execution":
            item = ItemRef("live_execution", ib_exec_id=item.ib_exec_id, account_id=item.account_id, con_id=item.con_id)
        by_item[item].append((link, tag))

    matches: dict[ItemRef, list[tuple[TagLink, Tag]]] = {}
    for item, pairs in by_item.items():
        values = {tag.normalized_value for _, tag in pairs}
        if want_all and not want_all <= values:
            continue
        if want_any and not want_any & values:
            continue
        if want_none & values:
            continue
        matches[item] = pairs

    descriptions: dict[str, dict[Any, dict[str, Any]]] = {}
    for kind in {item.entity_type for item in matches}:
        descriptions[kind] = describe_items(db, kind, [item_key(item) for item in matches if item.entity_type == kind])

    results = []
    for item, pairs in matches.items():
        details = dict(descriptions.get(item.entity_type, {}).get(item_key(item), {}))
        label = str(details.pop("label", item_key(item)))
        results.append(
            TaggedItem(
                entity_type=item.entity_type,
                id=item.id,
                account_id=item.account_id,
                con_id=item.con_id,
                ib_exec_id=item.ib_exec_id,
                label=label,
                details=details,
                tags=[TagChip(**tag_chip(tag, link)) for link, tag in sorted(pairs, key=lambda pair: pair[1].normalized_value)],
            )
        )
    results.sort(key=lambda row: (row.entity_type, str(row.details.get("executed_at") or ""), row.label), reverse=False)
    return TagSearchResponse(items=results)
