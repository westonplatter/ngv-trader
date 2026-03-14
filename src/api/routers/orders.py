"""Orders API router."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.routers.jobs import to_job_response
from src.models import Account, ContractRef, Order, OrderEvent
from src.services.jobs import JOB_TYPE_ORDER_FETCH_SYNC, enqueue_job
from src.services.order_mutations import OrderCreateInput, create_queued_order
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_QUEUED,
    ORDER_TERMINAL_STATUSES,
    transition_order_status,
)
from src.services.ui_events import TOPIC_JOBS, TOPIC_ORDERS, broadcaster, make_event
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class OrderCreateRequest(BaseModel):
    account_id: int
    symbol: str = Field(..., min_length=1)
    side: str = Field(..., pattern="^(BUY|SELL|buy|sell)$")
    quantity: int = Field(..., ge=1)
    sec_type: str = "FUT"
    exchange: str = "NYMEX"
    currency: str = "USD"
    order_type: str = "MKT"
    limit_price: float | None = Field(default=None, gt=0)
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
    limit_price: float | None
    tif: str
    status: str
    source: str
    con_id: int | None
    local_symbol: str | None
    trading_class: str | None
    contract_month: str | None
    contract_expiry: str | None
    option_right: str | None
    option_strike: str | None
    contract_display_name: str
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


class OrderSyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)
    host: str | None = None
    port: int | None = None
    client_id: int | None = None
    connect_timeout_seconds: float | None = Field(default=None, gt=0)


class OrderSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str
    max_attempts: int


def _derive_option_fields(order: Order) -> tuple[str | None, str | None]:
    if order.sec_type not in {"FOP", "OPT", "BAG"}:
        return None, None
    local_symbol = (order.local_symbol or "").strip().upper()
    if not local_symbol:
        return None, None

    # Examples:
    # - "WA4G6 C0707"
    # - "CL   MAY 26 70.5 C"
    compact_match = re.search(r"\b([CP])([0-9]{3,6})\b", local_symbol)
    if compact_match:
        return compact_match.group(1), compact_match.group(2)

    spaced_match = re.search(r"\b([CP])\s*([0-9]+(?:\.[0-9]+)?)\b", local_symbol)
    if spaced_match:
        return spaced_match.group(1), spaced_match.group(2)

    suffix_match = re.search(r"\b([0-9]+(?:\.[0-9]+)?)\s*([CP])\b", local_symbol)
    if suffix_match:
        return suffix_match.group(2), suffix_match.group(1)

    return None, None


def to_order_response(
    order: Order,
    account: Account | None,
    contract_ref: ContractRef | None = None,
) -> OrderResponse:
    alias = account.alias if account and account.alias else None
    effective_symbol = contract_ref.symbol if contract_ref and contract_ref.symbol else order.symbol
    effective_sec_type = contract_ref.sec_type if contract_ref and contract_ref.sec_type else order.sec_type
    effective_exchange = contract_ref.exchange if contract_ref and contract_ref.exchange else order.exchange
    effective_local_symbol = contract_ref.local_symbol if contract_ref and contract_ref.local_symbol else order.local_symbol
    effective_trading_class = contract_ref.trading_class if contract_ref and contract_ref.trading_class else order.trading_class
    effective_contract_month = contract_ref.contract_month if contract_ref and contract_ref.contract_month else order.contract_month
    effective_contract_expiry = contract_ref.contract_expiry if contract_ref and contract_ref.contract_expiry else order.contract_expiry
    effective_right = contract_ref.right if contract_ref and contract_ref.right else None
    effective_strike = contract_ref.strike if contract_ref and contract_ref.strike is not None else None

    option_right, option_strike = _derive_option_fields(order)
    if effective_right is not None:
        option_right = effective_right
    if effective_strike is not None:
        option_strike = f"{effective_strike:g}"

    return OrderResponse(
        id=order.id,
        account_id=order.account_id,
        account_alias=alias,
        symbol=effective_symbol,
        sec_type=effective_sec_type,
        exchange=effective_exchange,
        currency=order.currency,
        side=order.side,
        quantity=order.quantity,
        order_type=order.order_type,
        limit_price=order.limit_price,
        tif=order.tif,
        status=order.status,
        source=order.source,
        con_id=order.con_id,
        local_symbol=effective_local_symbol,
        trading_class=effective_trading_class,
        contract_month=effective_contract_month,
        contract_expiry=effective_contract_expiry,
        option_right=option_right,
        option_strike=option_strike,
        contract_display_name=contract_display_name(
            symbol=effective_symbol,
            sec_type=effective_sec_type,
            local_symbol=effective_local_symbol,
            right=option_right,
            strike=(float(option_strike) if option_strike is not None else None),
            contract_expiry=effective_contract_expiry,
            contract_month=effective_contract_month,
            exchange=effective_exchange,
            trading_class=effective_trading_class,
        ),
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
    stmt = (
        select(Order, Account, ContractRef)
        .outerjoin(Account, Order.account_id == Account.id)
        .outerjoin(ContractRef, Order.con_id == ContractRef.con_id)
        .order_by(Order.created_at.desc())
    )
    rows = db.execute(stmt).all()
    return [to_order_response(order, account, contract_ref) for order, account, contract_ref in rows]


@router.get("/orders/{order_id}", response_model=OrderResponse)
def get_order(order_id: int, db: Session = DB_SESSION_DEPENDENCY) -> OrderResponse:
    stmt = (
        select(Order, Account, ContractRef)
        .outerjoin(Account, Order.account_id == Account.id)
        .outerjoin(ContractRef, Order.con_id == ContractRef.con_id)
        .where(Order.id == order_id)
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order, account, contract_ref = row
    return to_order_response(order, account, contract_ref)


@router.post("/orders", response_model=OrderResponse, status_code=201)
def create_order(
    body: OrderCreateRequest,
    response: Response,
    db: Session = DB_SESSION_DEPENDENCY,
) -> OrderResponse:
    raise HTTPException(status_code=501, detail="Order creation is not supported at this time.")
    try:
        outcome = create_queued_order(
            db,
            OrderCreateInput(
                account_id=body.account_id,
                symbol=body.symbol,
                side=body.side,
                quantity=body.quantity,
                sec_type=body.sec_type,
                exchange=body.exchange,
                currency=body.currency,
                order_type=body.order_type,
                limit_price=body.limit_price,
                tif=body.tif,
                source=body.source,
                request_text=body.request_text,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not outcome.created:
        response.status_code = status.HTTP_200_OK

    db.commit()
    db.refresh(outcome.order)
    return to_order_response(outcome.order, outcome.account)


@router.post("/orders/sync", response_model=OrderSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_orders_sync(
    body: OrderSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> OrderSyncResponse:
    request_text = body.request_text or "Manual order fetch/sync request."
    payload: dict[str, str | int | float] = {}
    if body.host is not None:
        payload["host"] = body.host
    if body.port is not None:
        payload["port"] = body.port
    if body.client_id is not None:
        payload["client_id"] = body.client_id
    if body.connect_timeout_seconds is not None:
        payload["connect_timeout_seconds"] = body.connect_timeout_seconds

    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_ORDER_FETCH_SYNC,
        payload=payload,
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    db.refresh(job)
    broadcaster.publish(make_event(TOPIC_JOBS, "job.created", to_job_response(job), entity_id=job.id))
    return OrderSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )


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
    resp = to_order_response(order, account)
    broadcaster.publish(make_event(TOPIC_ORDERS, "order.cancelled", resp, entity_id=order.id))
    return resp
