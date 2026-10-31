"""Strategies API router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Strategy, TradeGroup
from src.services.strategies import normalize_strategy_name, require_strategy
from src.utils.sql import escape_like

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class StrategyResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str
    normalized_name: str
    created_by: str
    created_at: datetime
    archived_at: datetime | None


class StrategyCreateRequest(BaseModel):
    name: str
    created_by: str


class StrategyPatchRequest(BaseModel):
    name: str


@router.get("/strategies", response_model=list[StrategyResponse])
def list_strategies(
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    include_archived: bool = Query(default=False),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(Strategy)
    if not include_archived:
        stmt = stmt.where(Strategy.archived_at.is_(None))
    if q:
        stmt = stmt.where(Strategy.normalized_name.like(f"%{escape_like(normalize_strategy_name(q))}%", escape="\\"))
    rows = db.execute(stmt.order_by(Strategy.created_at.desc()).limit(limit)).scalars().all()
    return [StrategyResponse.model_validate(row) for row in rows]


@router.post("/strategies", response_model=StrategyResponse, status_code=201)
def create_strategy(body: StrategyCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    normalized_name = normalize_strategy_name(body.name)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="name cannot be empty")

    existing = db.execute(select(Strategy).where(Strategy.normalized_name == normalized_name)).scalar_one_or_none()
    if existing:
        return StrategyResponse.model_validate(existing)

    strategy = Strategy(
        name=body.name.strip(),
        normalized_name=normalized_name,
        created_by=body.created_by,
        created_at=_now_utc(),
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.patch("/strategies/{strategy_id}", response_model=StrategyResponse)
def patch_strategy(strategy_id: int, body: StrategyPatchRequest, db: Session = DB_SESSION_DEPENDENCY):
    strategy = require_strategy(db, strategy_id)
    normalized_name = normalize_strategy_name(body.name)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="name cannot be empty")

    duplicate = db.execute(select(Strategy).where(Strategy.normalized_name == normalized_name, Strategy.id != strategy_id)).scalar_one_or_none()
    if duplicate:
        raise HTTPException(status_code=409, detail="Strategy already exists")

    strategy.name = body.name.strip()
    strategy.normalized_name = normalized_name
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.post("/strategies/{strategy_id}/archive", response_model=StrategyResponse)
def archive_strategy(strategy_id: int, db: Session = DB_SESSION_DEPENDENCY):
    strategy = require_strategy(db, strategy_id)
    if strategy.archived_at is None:
        strategy.archived_at = _now_utc()
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.post("/strategies/{strategy_id}/unarchive", response_model=StrategyResponse)
def unarchive_strategy(strategy_id: int, db: Session = DB_SESSION_DEPENDENCY):
    strategy = require_strategy(db, strategy_id)
    if strategy.archived_at is not None:
        strategy.archived_at = None
        db.add(strategy)
        db.commit()
        db.refresh(strategy)
    return StrategyResponse.model_validate(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(strategy_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY):
    strategy = require_strategy(db, strategy_id)
    in_use = db.execute(select(func.count()).select_from(TradeGroup).where(TradeGroup.strategy_id == strategy_id)).scalar_one()
    if in_use:
        raise HTTPException(status_code=409, detail="Strategy is in use and cannot be deleted")

    db.delete(strategy)
    db.commit()
    response.status_code = 204
    return response
