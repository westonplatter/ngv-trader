"""Positions API router."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Position
from src.services.cl_contracts import infer_contract_month_from_local_symbol
from src.services.jobs import JOB_TYPE_POSITIONS_SYNC, enqueue_job
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class PositionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_alias: str
    contract_display_name: str
    con_id: int
    symbol: str | None
    sec_type: str | None
    exchange: str | None
    primary_exchange: str | None
    currency: str | None
    local_symbol: str | None
    trading_class: str | None
    last_trade_date: str | None
    option_expiry_date: str | None
    dte: int | None
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


def _parse_raw_expiry_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip()
    if len(value) >= 8 and value[:8].isdigit():
        try:
            return datetime.strptime(value[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _derive_option_expiry_and_dte(position: Position) -> tuple[str | None, int | None]:
    sec_type = (position.sec_type or "").strip().upper()
    expiry = _parse_raw_expiry_date(position.last_trade_date)
    if expiry is None:
        return None, None

    option_expiry_date = expiry.isoformat() if sec_type in {"OPT", "FOP"} else None
    return option_expiry_date, (expiry - date.today()).days


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
        option_expiry_date, dte = _derive_option_expiry_and_dte(pos)
        inferred_month = infer_contract_month_from_local_symbol(
            local_symbol=pos.local_symbol,
            contract_expiry=pos.last_trade_date,
            sec_type=pos.sec_type,
        )
        display_name = contract_display_name(
            symbol=pos.symbol,
            sec_type=pos.sec_type,
            local_symbol=pos.local_symbol,
            right=pos.right,
            strike=pos.strike,
            contract_expiry=pos.last_trade_date,
            contract_month=inferred_month,
            exchange=pos.exchange,
            trading_class=pos.trading_class,
        )
        results.append(
            PositionResponse(
                id=pos.id,
                account_alias=alias,
                contract_display_name=display_name,
                con_id=pos.con_id,
                symbol=pos.symbol,
                sec_type=pos.sec_type,
                exchange=pos.exchange,
                primary_exchange=pos.primary_exchange,
                currency=pos.currency,
                local_symbol=pos.local_symbol,
                trading_class=pos.trading_class,
                last_trade_date=pos.last_trade_date,
                option_expiry_date=option_expiry_date,
                dte=dte,
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
