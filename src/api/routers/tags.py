"""Tags, tag-links, strategies, and themes API router."""

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Tag, TagLink

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

TAG_TYPES = {"theme", "strategy", "risk_intent", "hedge_type", "holding_horizon"}
ENTITY_TYPES = {"orders", "trades", "trade_executions", "trade_groups"}
ASSIGNMENT_SOURCES = {"manual", "rule", "agent"}


def _normalize_tag_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_tag(db: Session, tag_id: int, expected_type: str) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail=f"{expected_type.title()} not found")
    if tag.tag_type != expected_type:
        raise HTTPException(status_code=400, detail=f"Tag {tag_id} is not a {expected_type}")
    return tag


def _create_tag_by_type(tag_type: str, value: str, created_by: str, db: Session) -> "TagResponse":
    normalized_value = _normalize_tag_value(value)
    if not normalized_value:
        raise HTTPException(status_code=400, detail="value cannot be empty")

    existing = db.execute(select(Tag).where(and_(Tag.tag_type == tag_type, Tag.normalized_value == normalized_value))).scalar_one_or_none()
    if existing:
        return TagResponse.model_validate(existing)

    tag = Tag(
        tag_type=tag_type,
        value=value.strip(),
        normalized_value=normalized_value,
        created_by=created_by,
        created_at=_now_utc(),
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagResponse.model_validate(tag)


class TagResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    tag_type: str
    value: str
    normalized_value: str
    created_by: str
    created_at: datetime


class TagLinkResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    entity_type: str
    entity_id: int
    tag_id: int
    tag_type: str
    is_primary: bool
    source: str
    created_by: str
    confidence: float | None
    assigned_at: datetime
    created_at: datetime


class TagCreateRequest(BaseModel):
    tag_type: str
    value: str
    created_by: str


class CatalogTagCreateRequest(BaseModel):
    value: str
    created_by: str


class TagPatchRequest(BaseModel):
    value: str


class TagLinkCreateRequest(BaseModel):
    entity_type: str
    entity_id: int
    tag_id: int
    is_primary: bool = False
    source: str
    created_by: str
    confidence: float | None = None


@router.get("/tags", response_model=list[TagResponse])
def list_tags(
    tag_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(Tag)
    if tag_type is not None:
        stmt = stmt.where(Tag.tag_type == tag_type)
    if q:
        stmt = stmt.where(Tag.normalized_value.like(f"%{_normalize_tag_value(q)}%"))
    rows = db.execute(stmt.order_by(Tag.created_at.desc()).limit(limit)).scalars().all()
    return [TagResponse.model_validate(row) for row in rows]


@router.post("/tags", response_model=TagResponse, status_code=201)
def create_tag(body: TagCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    if body.tag_type not in TAG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid tag_type")
    return _create_tag_by_type(body.tag_type, body.value, body.created_by, db)


@router.get("/strategies", response_model=list[TagResponse])
def list_strategies(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = DB_SESSION_DEPENDENCY,
):
    return list_tags(tag_type="strategy", q=q, limit=limit, db=db)


@router.post("/strategies", response_model=TagResponse, status_code=201)
def create_strategy(body: CatalogTagCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    return _create_tag_by_type("strategy", body.value, body.created_by, db)


@router.patch("/strategies/{strategy_id}", response_model=TagResponse)
def patch_strategy(strategy_id: int, body: TagPatchRequest, db: Session = DB_SESSION_DEPENDENCY):
    strategy = _ensure_tag(db, strategy_id, "strategy")
    normalized_value = _normalize_tag_value(body.value)
    if not normalized_value:
        raise HTTPException(status_code=400, detail="value cannot be empty")

    duplicate = db.execute(
        select(Tag).where(
            and_(
                Tag.tag_type == "strategy",
                Tag.normalized_value == normalized_value,
                Tag.id != strategy_id,
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Strategy already exists")

    strategy.value = body.value.strip()
    strategy.normalized_value = normalized_value
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return TagResponse.model_validate(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY):
    strategy = _ensure_tag(db, strategy_id, "strategy")
    has_links = db.execute(select(func.count()).select_from(TagLink).where(TagLink.tag_id == strategy_id)).scalar_one()
    if has_links:
        raise HTTPException(status_code=409, detail="Strategy is in use and cannot be deleted")

    db.delete(strategy)
    db.commit()
    response.status_code = 204
    return response


@router.get("/themes", response_model=list[TagResponse])
def list_themes(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = DB_SESSION_DEPENDENCY,
):
    return list_tags(tag_type="theme", q=q, limit=limit, db=db)


@router.post("/themes", response_model=TagResponse, status_code=201)
def create_theme(body: CatalogTagCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    return _create_tag_by_type("theme", body.value, body.created_by, db)


@router.patch("/themes/{theme_id}", response_model=TagResponse)
def patch_theme(theme_id: int, body: TagPatchRequest, db: Session = DB_SESSION_DEPENDENCY):
    theme = _ensure_tag(db, theme_id, "theme")
    normalized_value = _normalize_tag_value(body.value)
    if not normalized_value:
        raise HTTPException(status_code=400, detail="value cannot be empty")

    duplicate = db.execute(
        select(Tag).where(
            and_(
                Tag.tag_type == "theme",
                Tag.normalized_value == normalized_value,
                Tag.id != theme_id,
            )
        )
    ).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Theme already exists")

    theme.value = body.value.strip()
    theme.normalized_value = normalized_value
    db.add(theme)
    db.commit()
    db.refresh(theme)
    return TagResponse.model_validate(theme)


@router.delete("/themes/{theme_id}", status_code=204)
def delete_theme(theme_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY):
    theme = _ensure_tag(db, theme_id, "theme")
    has_links = db.execute(select(func.count()).select_from(TagLink).where(TagLink.tag_id == theme_id)).scalar_one()
    if has_links:
        raise HTTPException(status_code=409, detail="Theme is in use and cannot be deleted")

    db.delete(theme)
    db.commit()
    response.status_code = 204
    return response


@router.post("/tag-links", response_model=TagLinkResponse, status_code=201)
def create_tag_link(body: TagLinkCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    if body.entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity_type")
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    tag = db.get(Tag, body.tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    tag_link = TagLink(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        tag_id=body.tag_id,
        tag_type=tag.tag_type,
        is_primary=body.is_primary,
        source=body.source,
        created_by=body.created_by,
        confidence=body.confidence,
        assigned_at=_now_utc(),
        created_at=_now_utc(),
    )

    if (
        body.entity_type == "trade_groups"
        and tag.tag_type == "strategy"
        and body.is_primary
        and db.execute(
            select(TagLink).where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == body.entity_id,
                    TagLink.tag_type == "strategy",
                    TagLink.is_primary.is_(True),
                )
            )
        ).scalar_one_or_none()
    ):
        raise HTTPException(status_code=409, detail="Trade group already has a primary strategy")

    db.add(tag_link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tag link conflict") from exc
    db.refresh(tag_link)
    return TagLinkResponse.model_validate(tag_link)


@router.delete("/tag-links/{tag_link_id}", status_code=204)
def delete_tag_link(tag_link_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY):
    tag_link = db.get(TagLink, tag_link_id)
    if tag_link is None:
        raise HTTPException(status_code=404, detail="Tag link not found")
    db.delete(tag_link)
    db.commit()
    response.status_code = 204
    return response
