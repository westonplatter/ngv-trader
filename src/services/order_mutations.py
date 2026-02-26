"""Shared order mutation helpers used by API and Tradebot paths."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Account, Order
from src.services.order_queue import ORDER_STATUS_QUEUED, append_order_event, now_utc

IDEMPOTENT_CREATE_WINDOW_SECONDS = 30
IDEMPOTENT_CREATE_STATUSES = {
    "queued",
    "submitting",
    "submitted",
    "partially_filled",
    "reconcile_required",
}


@dataclass(frozen=True)
class OrderCreateInput:
    account_id: int
    symbol: str
    side: str
    quantity: int
    sec_type: str = "FUT"
    exchange: str = "NYMEX"
    currency: str = "USD"
    order_type: str = "MKT"
    limit_price: float | None = None
    tif: str = "DAY"
    source: str = "manual"
    request_text: str | None = None


@dataclass(frozen=True)
class OrderCreateOutcome:
    order: Order
    account: Account
    created: bool


def normalize_order_create_input(raw: OrderCreateInput) -> OrderCreateInput:
    symbol = raw.symbol.strip().upper()
    side = raw.side.strip().upper()
    sec_type = raw.sec_type.strip().upper()
    exchange = raw.exchange.strip().upper()
    currency = raw.currency.strip().upper()
    order_type = raw.order_type.strip().upper()
    tif = raw.tif.strip().upper()
    source = raw.source.strip()
    request_text = raw.request_text.strip() if raw.request_text else None
    limit_price = float(raw.limit_price) if raw.limit_price is not None else None

    if not symbol:
        raise ValueError("'symbol' must be a non-empty string.")
    if symbol.startswith("/"):
        if sec_type != "FUT":
            raise ValueError("Slash-prefixed symbols are only supported for FUT orders.")
        if len(symbol) == 1 or not symbol[1:].strip():
            raise ValueError("Slash-prefixed symbols must include a root symbol, e.g. '/MCL'.")
    if side not in {"BUY", "SELL"}:
        raise ValueError("'side' must be BUY or SELL.")
    if raw.quantity < 1:
        raise ValueError("'quantity' must be >= 1.")
    if not sec_type:
        raise ValueError("'sec_type' must be a non-empty string.")
    if not exchange:
        raise ValueError("'exchange' must be a non-empty string.")
    if not currency:
        raise ValueError("'currency' must be a non-empty string.")
    if order_type not in {"MKT", "LMT"}:
        raise ValueError("'order_type' must be MKT or LMT.")
    if order_type == "LMT" and (limit_price is None or limit_price <= 0):
        raise ValueError("'limit_price' must be > 0 for LMT orders.")
    if order_type == "MKT":
        limit_price = None
    if not tif:
        raise ValueError("'tif' must be a non-empty string.")
    if not source:
        raise ValueError("'source' must be a non-empty string.")

    return OrderCreateInput(
        account_id=raw.account_id,
        symbol=symbol,
        side=side,
        quantity=raw.quantity,
        sec_type=sec_type,
        exchange=exchange,
        currency=currency,
        order_type=order_type,
        limit_price=limit_price,
        tif=tif,
        source=source,
        request_text=request_text,
    )


def find_idempotent_create_match(
    session: Session,
    order_input: OrderCreateInput,
    *,
    window_seconds: int = IDEMPOTENT_CREATE_WINDOW_SECONDS,
) -> Order | None:
    now = now_utc()
    min_created_at = now - timedelta(seconds=window_seconds)
    stmt = (
        select(Order)
        .where(
            Order.account_id == order_input.account_id,
            Order.symbol == order_input.symbol,
            Order.sec_type == order_input.sec_type,
            Order.exchange == order_input.exchange,
            Order.currency == order_input.currency,
            Order.side == order_input.side,
            Order.quantity == order_input.quantity,
            Order.order_type == order_input.order_type,
            Order.limit_price == order_input.limit_price,
            Order.tif == order_input.tif,
            Order.source == order_input.source,
            Order.request_text == order_input.request_text,
            Order.status.in_(IDEMPOTENT_CREATE_STATUSES),
            Order.created_at >= min_created_at,
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def create_queued_order(
    session: Session,
    order_input: OrderCreateInput,
    *,
    idempotent_window_seconds: int = IDEMPOTENT_CREATE_WINDOW_SECONDS,
) -> OrderCreateOutcome:
    normalized = normalize_order_create_input(order_input)
    account = session.get(Account, normalized.account_id)
    if account is None:
        raise ValueError("Invalid account_id")

    existing = find_idempotent_create_match(
        session,
        normalized,
        window_seconds=idempotent_window_seconds,
    )
    if existing is not None:
        return OrderCreateOutcome(order=existing, account=account, created=False)

    created_at = now_utc()
    order = Order(
        account_id=normalized.account_id,
        symbol=normalized.symbol,
        sec_type=normalized.sec_type,
        exchange=normalized.exchange,
        currency=normalized.currency,
        side=normalized.side,
        quantity=normalized.quantity,
        order_type=normalized.order_type,
        limit_price=normalized.limit_price,
        tif=normalized.tif,
        status=ORDER_STATUS_QUEUED,
        source=normalized.source,
        request_text=normalized.request_text,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(order)
    session.flush()

    append_order_event(
        session=session,
        order_id=order.id,
        event_type="order_created",
        message="Order queued for worker execution.",
        status=order.status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
    return OrderCreateOutcome(order=order, account=account, created=True)
