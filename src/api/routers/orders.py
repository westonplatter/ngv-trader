"""Orders API router."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, Order, OrderEvent
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_RECONCILE_REQUIRED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_SUBMITTING,
    ORDER_TERMINAL_STATUSES,
    append_order_event,
    now_utc,
    transition_order_status,
)

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)
IDEMPOTENT_CREATE_WINDOW_SECONDS = 30
IDEMPOTENT_CREATE_STATUSES = {
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_SUBMITTING,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_RECONCILE_REQUIRED,
}


class OrderCreateRequest(BaseModel):
    account_id: int
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(BUY|SELL|buy|sell)$")
    quantity: int = Field(..., ge=1)
    sec_type: str = "FUT"
    exchange: str = "NYMEX"
    currency: str = "USD"
    order_type: str = "MKT"
    tif: str = "DAY"
    source: str = Field(default="manual", min_length=1)
    request_text: str | None = None


class OrderCancelRequest(BaseModel):
    source: str = Field(default="manual", min_length=1)
    request_text: str | None = None


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


def _find_idempotent_create_match(db: Session, body: OrderCreateRequest) -> tuple[Order, Account | None] | None:
    now = now_utc()
    min_created_at = now - timedelta(seconds=IDEMPOTENT_CREATE_WINDOW_SECONDS)
    stmt = (
        select(Order, Account)
        .outerjoin(Account, Order.account_id == Account.id)
        .where(
            Order.account_id == body.account_id,
            Order.symbol == body.symbol.upper(),
            Order.sec_type == body.sec_type.upper(),
            Order.exchange == body.exchange.upper(),
            Order.currency == body.currency.upper(),
            Order.side == body.side.upper(),
            Order.quantity == body.quantity,
            Order.order_type == body.order_type.upper(),
            Order.tif == body.tif.upper(),
            Order.source == body.source,
            Order.request_text == body.request_text,
            Order.status.in_(IDEMPOTENT_CREATE_STATUSES),
            Order.created_at >= min_created_at,
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        return None
    order, account = row
    return order, account


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


@router.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(
    body: OrderCreateRequest,
    response: Response,
    db: Session = DB_SESSION_DEPENDENCY,
) -> OrderResponse:
    account = db.get(Account, body.account_id)
    if account is None:
        raise HTTPException(status_code=400, detail="Invalid account_id")

    existing = _find_idempotent_create_match(db, body)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        order, matched_account = existing
        return to_order_response(order, matched_account)

    created_at = now_utc()
    order = Order(
        account_id=body.account_id,
        symbol=body.symbol.upper(),
        sec_type=body.sec_type.upper(),
        exchange=body.exchange.upper(),
        currency=body.currency.upper(),
        side=body.side.upper(),
        quantity=body.quantity,
        order_type=body.order_type.upper(),
        tif=body.tif.upper(),
        status=ORDER_STATUS_QUEUED,
        source=body.source,
        request_text=body.request_text,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(order)
    db.flush()

    append_order_event(
        session=db,
        order_id=order.id,
        event_type="order_created",
        message="Order queued for worker execution.",
        status=order.status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
    db.commit()
    db.refresh(order)
    return to_order_response(order, account)


@router.get("/orders/{order_id}/events", response_model=list[OrderEventResponse])
def list_order_events(order_id: int, db: Session = DB_SESSION_DEPENDENCY) -> list[OrderEventResponse]:
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    stmt = select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.created_at)
    events = list(db.execute(stmt).scalars().all())
    return [to_order_event_response(event) for event in events]


@router.post("/orders/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: int,
    body: OrderCancelRequest | None = None,
    db: Session = DB_SESSION_DEPENDENCY,
) -> OrderResponse:
    stmt = select(Order, Account).outerjoin(Account, Order.account_id == Account.id).where(Order.id == order_id)
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")

    order, account = row
    if order.status in ORDER_TERMINAL_STATUSES:
        return to_order_response(order, account)

    if order.status != ORDER_STATUS_QUEUED:
        raise HTTPException(
            status_code=400,
            detail=("Only queued orders can be cancelled from the API right now. " f"Current status is '{order.status}'."),
        )

    cancel_reason = "Cancelled via API before worker submission."
    if body is not None and body.request_text:
        cancel_reason = body.request_text.strip()
    transition_order_status(
        session=db,
        order=order,
        next_status=ORDER_STATUS_CANCELLED,
        event_type="order_cancelled",
        message=cancel_reason,
    )
    db.commit()
    db.refresh(order)
    return to_order_response(order, account)
