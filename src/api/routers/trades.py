"""Trades API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Trade, TradeExecution
from src.services.jobs import JOB_TYPE_TRADES_SYNC, enqueue_job

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


def _contract_display_from_raw(raw: dict | None) -> str | None:
    """Extract a human-readable contract label from the execution's raw JSON."""
    if not raw:
        return None
    contract = raw.get("contract")
    if not contract:
        return None
    local_symbol = (contract.get("localSymbol") or "").strip()
    sec_type = (contract.get("secType") or "").strip().upper()
    symbol = (contract.get("symbol") or "").strip().upper()
    # For BAG (combo summary), localSymbol is often empty — show "symbol BAG"
    if sec_type == "BAG":
        return f"{symbol} Combo" if symbol else "Combo"
    # localSymbol is the most compact IBKR-native label (e.g. "CLU6", "LO CL 27FEB26 62.75 P")
    if local_symbol:
        return local_symbol
    if symbol:
        return symbol
    return None


class TradeResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str | None
    ib_perm_id: int | None
    order_ref: str | None
    ib_order_id: int | None
    symbol: str | None
    sec_type: str | None
    side: str | None
    exchange: str | None
    currency: str | None
    status: str
    total_quantity: float
    avg_price: float | None
    first_executed_at: datetime | None
    last_executed_at: datetime | None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TradeExecutionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    trade_id: int
    account_id: int
    ib_exec_id: str
    exec_id_base: str
    exec_revision: int
    ib_perm_id: int | None
    ib_order_id: int | None
    order_ref: str | None
    sec_type: str | None
    con_id: int | None
    exec_role: str
    executed_at: datetime
    quantity: float
    price: float
    side: str | None
    exchange: str | None
    currency: str | None
    liquidity: str | None
    commission: float | None
    is_canonical: bool
    contract_display: str | None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TradeSyncRequest(BaseModel):
    source: str = "manual-ui"
    request_text: str | None = None
    lookback_days: int = 7
    max_attempts: int = 3


class TradeSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str


@router.get("/trades", response_model=list[TradeResponse])
def list_trades(
    account_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(Trade, Account).outerjoin(Account, Trade.account_id == Account.id)

    if account_id is not None:
        stmt = stmt.where(Trade.account_id == account_id)
    if status_filter is not None:
        stmt = stmt.where(Trade.status == status_filter)
    if symbol is not None:
        stmt = stmt.where(Trade.symbol == symbol.upper())

    stmt = stmt.order_by(Trade.last_executed_at.desc().nullslast()).limit(limit)
    rows = db.execute(stmt).all()

    results = []
    for trade, acct in rows:
        alias = None
        if acct:
            alias = acct.alias if acct.alias else acct.account
        results.append(
            TradeResponse(
                id=trade.id,
                account_id=trade.account_id,
                account_alias=alias,
                ib_perm_id=trade.ib_perm_id,
                order_ref=trade.order_ref,
                ib_order_id=trade.ib_order_id,
                symbol=trade.symbol,
                sec_type=trade.sec_type,
                side=trade.side,
                exchange=trade.exchange,
                currency=trade.currency,
                status=trade.status,
                total_quantity=trade.total_quantity,
                avg_price=trade.avg_price,
                first_executed_at=trade.first_executed_at,
                last_executed_at=trade.last_executed_at,
                fetched_at=trade.fetched_at,
                created_at=trade.created_at,
                updated_at=trade.updated_at,
            )
        )
    return results


@router.get("/trades/{trade_id}", response_model=TradeResponse)
def get_trade(trade_id: int, db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(Trade, Account).outerjoin(Account, Trade.account_id == Account.id).where(Trade.id == trade_id)
    row = db.execute(stmt).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    trade, acct = row
    alias = None
    if acct:
        alias = acct.alias if acct.alias else acct.account
    return TradeResponse(
        id=trade.id,
        account_id=trade.account_id,
        account_alias=alias,
        ib_perm_id=trade.ib_perm_id,
        order_ref=trade.order_ref,
        ib_order_id=trade.ib_order_id,
        symbol=trade.symbol,
        sec_type=trade.sec_type,
        side=trade.side,
        exchange=trade.exchange,
        currency=trade.currency,
        status=trade.status,
        total_quantity=trade.total_quantity,
        avg_price=trade.avg_price,
        first_executed_at=trade.first_executed_at,
        last_executed_at=trade.last_executed_at,
        fetched_at=trade.fetched_at,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )


@router.get("/trades/{trade_id}/executions", response_model=list[TradeExecutionResponse])
def list_trade_executions(trade_id: int, db: Session = DB_SESSION_DEPENDENCY):
    # Verify trade exists
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    stmt = select(TradeExecution).where(TradeExecution.trade_id == trade_id).order_by(TradeExecution.executed_at.asc())
    executions = db.execute(stmt).scalars().all()
    return [
        TradeExecutionResponse(
            id=ex.id,
            trade_id=ex.trade_id,
            account_id=ex.account_id,
            ib_exec_id=ex.ib_exec_id,
            exec_id_base=ex.exec_id_base,
            exec_revision=ex.exec_revision,
            ib_perm_id=ex.ib_perm_id,
            ib_order_id=ex.ib_order_id,
            order_ref=ex.order_ref,
            sec_type=ex.sec_type,
            con_id=ex.con_id,
            exec_role=ex.exec_role,
            executed_at=ex.executed_at,
            quantity=ex.quantity,
            price=ex.price,
            side=ex.side,
            exchange=ex.exchange,
            currency=ex.currency,
            liquidity=ex.liquidity,
            commission=ex.commission,
            is_canonical=ex.is_canonical,
            contract_display=_contract_display_from_raw(ex.raw),
            fetched_at=ex.fetched_at,
            created_at=ex.created_at,
            updated_at=ex.updated_at,
        )
        for ex in executions
    ]


@router.post("/trades/sync", response_model=TradeSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_trades_sync(
    body: TradeSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    request_text = body.request_text or "Manual trades sync."
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_TRADES_SYNC,
        payload={"lookback_days": body.lookback_days},
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    return TradeSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
    )
