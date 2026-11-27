"""Orders API router."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.schemas import (
    OrderResponse,
    OrderStreamStatusResponse,
    load_order_legs,
    to_job_response,
    to_order_response,
)
from src.models import Account, ContractRef, Order, OrderEvent, WorkerHeartbeat
from src.services.jobs import JOB_TYPE_ORDER_FETCH_SYNC, enqueue_job
from src.services.order_mutations import OrderCreateInput, create_queued_order
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_QUEUED,
    ORDER_TERMINAL_STATUSES,
    transition_order_status,
)
from src.services.ui_events import TOPIC_JOBS, TOPIC_ORDERS, broadcaster, make_event
from src.services.worker_heartbeat import WORKER_TYPE_ORDER_STREAM, YELLOW_SECONDS
from src.utils.time import now_utc

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
    legs = load_order_legs(db, [order for order, _, _ in rows])
    return [to_order_response(order, account, contract_ref, legs.get(order.id)) for order, account, contract_ref in rows]


def _stream_details(details: str | None) -> dict:
    try:
        parsed = json.loads(details or "")
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def to_stream_status_response(row: WorkerHeartbeat | None, now: datetime) -> OrderStreamStatusResponse:
    if row is None:
        return OrderStreamStatusResponse(state="disabled", stream_state=None, last_event_at=None, heartbeat_at=None, seconds_since_heartbeat=None)
    details = _stream_details(row.details)
    seconds_since = max(0.0, (now - row.heartbeat_at).total_seconds())
    stream_state = details.get("state")
    live = row.status == "running" and seconds_since <= YELLOW_SECONDS and stream_state == "live"
    last_event_at = details.get("last_event_at")
    return OrderStreamStatusResponse(
        state="live" if live else "not_live",
        stream_state=stream_state if isinstance(stream_state, str) else None,
        last_event_at=datetime.fromisoformat(last_event_at) if isinstance(last_event_at, str) else None,
        heartbeat_at=row.heartbeat_at,
        seconds_since_heartbeat=seconds_since,
    )


# Registered before /orders/{order_id} so the literal path is not read as an id.
@router.get("/orders/stream-status", response_model=OrderStreamStatusResponse)
def get_order_stream_status(db: Session = DB_SESSION_DEPENDENCY) -> OrderStreamStatusResponse:
    row = db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_type == WORKER_TYPE_ORDER_STREAM)).scalar_one_or_none()
    return to_stream_status_response(row, now_utc())


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
    return to_order_response(order, account, contract_ref, load_order_legs(db, [order]).get(order.id))


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
            detail=(f"Only queued orders can be cancelled from the API right now. Current status is '{order.status}'."),
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
