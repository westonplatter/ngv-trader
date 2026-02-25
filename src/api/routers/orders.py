"""Orders API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Order, OrderEvent

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class OrderResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str | None
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    side: str
    quantity: int
    order_type: str
    tif: str
    status: str
    source: str
    con_id: int | None
    local_symbol: str | None
    trading_class: str | None
    contract_month: str | None
    contract_expiry: str | None
    ib_order_id: int | None
    ib_perm_id: int | None
    filled_quantity: float
    avg_fill_price: float | None
    last_error: str | None
    request_text: str | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrderEventResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    order_id: int
    event_type: str
    message: str
    status: str | None
    filled_quantity: float | None
    avg_fill_price: float | None
    ib_order_id: int | None
    created_at: datetime


def to_order_response(order: Order, account: Account | None) -> OrderResponse:
    alias = account.alias if account and account.alias else None
    return OrderResponse(
        id=order.id,
        account_id=order.account_id,
        account_alias=alias,
        symbol=order.symbol,
        sec_type=order.sec_type,
        exchange=order.exchange,
        currency=order.currency,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type,
        tif=order.tif,
        status=order.status,
        source=order.source,
        con_id=order.con_id,
        local_symbol=order.local_symbol,
        trading_class=order.trading_class,
        contract_month=order.contract_month,
        contract_expiry=order.contract_expiry,
        ib_order_id=order.ib_order_id,
        ib_perm_id=order.ib_perm_id,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        last_error=order.last_error,
        request_text=order.request_text,
        submitted_at=order.submitted_at,
        completed_at=order.completed_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


def to_order_event_response(event: OrderEvent) -> OrderEventResponse:
    return OrderEventResponse(
        id=event.id,
        order_id=event.order_id,
        event_type=event.event_type,
        message=event.message,
        status=event.status,
        filled_quantity=event.filled_quantity,
        avg_fill_price=event.avg_fill_price,
        ib_order_id=event.ib_order_id,
        created_at=event.created_at,
    )


@router.get("/orders", response_model=list[OrderResponse])
def list_orders(db: Session = DB_SESSION_DEPENDENCY) -> list[OrderResponse]:
    stmt = select(Order, Account).outerjoin(Account, Order.account_id == Account.id).order_by(Order.created_at.desc())
    rows = db.execute(stmt).all()
    return [to_order_response(order, account) for order, account in rows]


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = DB_SESSION_DEPENDENCY) -> OrderResponse:
    stmt = select(Order, Account).outerjoin(Account, Order.account_id == Account.id).where(Order.id == order_id)
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order, account = row
    return to_order_response(order, account)


@router.get("/orders/{order_id}/events", response_model=list[OrderEventResponse])
def list_order_events(order_id: int, db: Session = DB_SESSION_DEPENDENCY) -> list[OrderEventResponse]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    stmt = select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.created_at)
    events = list(db.execute(stmt).scalars().all())
    return [to_order_event_response(event) for event in events]
