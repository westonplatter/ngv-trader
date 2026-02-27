"""Spreads API router — combo/spread positions from TWS BAG positions."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, ComboPosition, ComboPositionLeg, Position
from src.services.jobs import JOB_TYPE_COMBO_POSITIONS_SYNC, enqueue_job

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


# -- Response schemas ----------------------------------------------------------


class LegResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    con_id: int
    ratio: float | None
    position: float | None
    avg_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None


class SpreadResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str
    source: str
    combo_key: str
    name: str | None
    description: str | None
    position: float | None
    avg_price: float | None
    market_value: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None
    fetched_at: datetime
    legs: list[LegResponse]


class UnmatchedLegResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_alias: str
    con_id: int
    symbol: str | None
    local_symbol: str | None
    sec_type: str | None
    last_trade_date: str | None
    position: float
    avg_cost: float
    fetched_at: datetime


class SpreadSyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class SpreadSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str
    max_attempts: int


# -- Helpers -------------------------------------------------------------------


def _account_alias(acct: Account | None, account_id: int) -> str:
    if acct:
        return acct.alias if acct.alias else f"Account Alias {acct.id}"
    return f"Unknown Account {account_id}"


# -- Endpoints -----------------------------------------------------------------


@router.get("/spreads", response_model=list[SpreadResponse])
def list_spreads(
    db: Session = DB_SESSION_DEPENDENCY,
    account_id: int | None = Query(default=None),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    stmt = select(ComboPosition, Account).outerjoin(Account, ComboPosition.account_id == Account.id).order_by(ComboPosition.fetched_at.desc()).limit(limit)
    if account_id is not None:
        stmt = stmt.where(ComboPosition.account_id == account_id)
    if symbol is not None:
        # Filter by symbol appearing in name or description (CL spreads etc.)
        pattern = f"%{symbol}%"
        stmt = stmt.where(ComboPosition.name.ilike(pattern) | ComboPosition.description.ilike(pattern))

    rows = db.execute(stmt).all()
    results = []
    for combo, acct in rows:
        legs = db.execute(select(ComboPositionLeg).where(ComboPositionLeg.combo_position_id == combo.id).order_by(ComboPositionLeg.con_id)).scalars().all()
        results.append(
            SpreadResponse(
                id=combo.id,
                account_id=combo.account_id,
                account_alias=_account_alias(acct, combo.account_id),
                source=combo.source,
                combo_key=combo.combo_key,
                name=combo.name,
                description=combo.description,
                position=combo.position,
                avg_price=combo.avg_price,
                market_value=combo.market_value,
                unrealized_pnl=combo.unrealized_pnl,
                realized_pnl=combo.realized_pnl,
                fetched_at=combo.fetched_at,
                legs=[
                    LegResponse(
                        id=leg.id,
                        con_id=leg.con_id,
                        ratio=leg.ratio,
                        position=leg.position,
                        avg_price=leg.avg_price,
                        market_value=leg.market_value,
                        unrealized_pnl=leg.unrealized_pnl,
                        realized_pnl=leg.realized_pnl,
                    )
                    for leg in legs
                ],
            )
        )
    return results


@router.get("/spreads/{spread_id}", response_model=SpreadResponse)
def get_spread(spread_id: int, db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(ComboPosition, Account).outerjoin(Account, ComboPosition.account_id == Account.id).where(ComboPosition.id == spread_id)
    row = db.execute(stmt).first()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Spread not found")

    combo, acct = row
    legs = db.execute(select(ComboPositionLeg).where(ComboPositionLeg.combo_position_id == combo.id).order_by(ComboPositionLeg.con_id)).scalars().all()
    return SpreadResponse(
        id=combo.id,
        account_id=combo.account_id,
        account_alias=_account_alias(acct, combo.account_id),
        source=combo.source,
        combo_key=combo.combo_key,
        name=combo.name,
        description=combo.description,
        position=combo.position,
        avg_price=combo.avg_price,
        market_value=combo.market_value,
        unrealized_pnl=combo.unrealized_pnl,
        realized_pnl=combo.realized_pnl,
        fetched_at=combo.fetched_at,
        legs=[
            LegResponse(
                id=leg.id,
                con_id=leg.con_id,
                ratio=leg.ratio,
                position=leg.position,
                avg_price=leg.avg_price,
                market_value=leg.market_value,
                unrealized_pnl=leg.unrealized_pnl,
                realized_pnl=leg.realized_pnl,
            )
            for leg in legs
        ],
    )


@router.get("/spreads/unmatched-legs", response_model=list[UnmatchedLegResponse])
def list_unmatched_legs(
    db: Session = DB_SESSION_DEPENDENCY,
    symbol: str = Query(default="CL"),
):
    """CL legs that are not part of any combo position."""
    # Get all con_ids currently in combo legs
    combo_con_ids_stmt = select(ComboPositionLeg.con_id).distinct()
    combo_con_ids = set(db.execute(combo_con_ids_stmt).scalars().all())

    # Get CL positions not in any combo
    stmt = select(Position, Account).outerjoin(Account, Position.account_id == Account.id).where(Position.symbol == symbol).order_by(Position.id)
    rows = db.execute(stmt).all()
    results = []
    for pos, acct in rows:
        if pos.con_id in combo_con_ids:
            continue
        results.append(
            UnmatchedLegResponse(
                id=pos.id,
                account_alias=_account_alias(acct, pos.account_id),
                con_id=pos.con_id,
                symbol=pos.symbol,
                local_symbol=pos.local_symbol,
                sec_type=pos.sec_type,
                last_trade_date=pos.last_trade_date,
                position=pos.position,
                avg_cost=pos.avg_cost,
                fetched_at=pos.fetched_at,
            )
        )
    return results


@router.post("/spreads/sync", response_model=SpreadSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_spreads_sync(
    body: SpreadSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> SpreadSyncResponse:
    request_text = body.request_text or "Manual combo positions sync from UI."
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_COMBO_POSITIONS_SYNC,
        payload={},
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    return SpreadSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )
