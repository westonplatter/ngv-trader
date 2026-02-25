"""Positions API router."""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Position

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
