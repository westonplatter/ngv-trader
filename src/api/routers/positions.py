"""Positions API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Position
from src.services.jobs import JOB_TYPE_POSITIONS_SYNC, enqueue_job

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class PositionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_alias: str
    con_id: int
    symbol: str | None
    sec_type: str | None
    exchange: str | None
    primary_exchange: str | None
    currency: str | None
    local_symbol: str | None
    trading_class: str | None
    last_trade_date: str | None
    strike: float | None
    right: str | None
    multiplier: str | None
    position: float
    avg_cost: float
    fetched_at: datetime


class PositionSyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class PositionSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str
    max_attempts: int


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(Position, Account).outerjoin(Account, Position.account_id == Account.id)
    rows = db.execute(stmt).all()
    results = []
    for pos, acct in rows:
        if acct:
            alias = acct.alias if acct.alias else f"Account Alias {acct.id}"
        else:
            alias = f"Unknown Account {pos.account_id}"
        results.append(
            PositionResponse(
                id=pos.id,
                account_alias=alias,
                con_id=pos.con_id,
                symbol=pos.symbol,
                sec_type=pos.sec_type,
                exchange=pos.exchange,
                primary_exchange=pos.primary_exchange,
                currency=pos.currency,
                local_symbol=pos.local_symbol,
                trading_class=pos.trading_class,
                last_trade_date=pos.last_trade_date,
                strike=pos.strike,
                right=pos.right,
                multiplier=pos.multiplier,
                position=pos.position,
                avg_cost=pos.avg_cost,
                fetched_at=pos.fetched_at,
            )
        )
    return results


@router.post("/positions/sync", response_model=PositionSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_positions_sync(
    body: PositionSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> PositionSyncResponse:
    request_text = body.request_text or "Manual positions sync from UI."
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_POSITIONS_SYNC,
        payload={},
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    return PositionSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )
