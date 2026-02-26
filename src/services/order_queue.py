"""Order queue domain primitives.

This module intentionally contains no broker I/O. It only provides shared order
state and event helpers used by API/worker layers.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.models import Order, OrderEvent

ORDER_STATUS_QUEUED = "queued"
ORDER_STATUS_SUBMITTING = "submitting"
ORDER_STATUS_SUBMITTED = "submitted"
ORDER_STATUS_PARTIALLY_FILLED = "partially_filled"
ORDER_STATUS_FILLED = "filled"
ORDER_STATUS_CANCELLED = "cancelled"
ORDER_STATUS_REJECTED = "rejected"
ORDER_STATUS_FAILED = "failed"
ORDER_STATUS_RECONCILE_REQUIRED = "reconcile_required"

ORDER_TERMINAL_STATUSES = {
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_FAILED,
}

ALLOWED_ORDER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    ORDER_STATUS_QUEUED: {
        ORDER_STATUS_SUBMITTING,
        ORDER_STATUS_CANCELLED,
        ORDER_STATUS_FAILED,
    },
    ORDER_STATUS_SUBMITTING: {
        ORDER_STATUS_SUBMITTED,
        ORDER_STATUS_PARTIALLY_FILLED,
        ORDER_STATUS_REJECTED,
        ORDER_STATUS_FAILED,
        ORDER_STATUS_RECONCILE_REQUIRED,
    },
    ORDER_STATUS_SUBMITTED: {
        ORDER_STATUS_PARTIALLY_FILLED,
        ORDER_STATUS_FILLED,
        ORDER_STATUS_CANCELLED,
        ORDER_STATUS_REJECTED,
        ORDER_STATUS_FAILED,
        ORDER_STATUS_RECONCILE_REQUIRED,
    },
    ORDER_STATUS_PARTIALLY_FILLED: {
        ORDER_STATUS_PARTIALLY_FILLED,
        ORDER_STATUS_FILLED,
        ORDER_STATUS_CANCELLED,
        ORDER_STATUS_RECONCILE_REQUIRED,
        ORDER_STATUS_FAILED,
    },
    ORDER_STATUS_RECONCILE_REQUIRED: {
        ORDER_STATUS_SUBMITTING,
        ORDER_STATUS_SUBMITTED,
        ORDER_STATUS_PARTIALLY_FILLED,
        ORDER_STATUS_FILLED,
        ORDER_STATUS_CANCELLED,
        ORDER_STATUS_REJECTED,
        ORDER_STATUS_FAILED,
    },
    ORDER_STATUS_FILLED: set(),
    ORDER_STATUS_CANCELLED: set(),
    ORDER_STATUS_REJECTED: set(),
    ORDER_STATUS_FAILED: set(),
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def can_transition_order_status(current_status: str, next_status: str) -> bool:
    allowed = ALLOWED_ORDER_STATUS_TRANSITIONS.get(current_status)
    if allowed is None:
        return False
    return next_status in allowed


def append_order_event(
    session: Session,
    order_id: int,
    event_type: str,
    message: str,
    *,
    status: str | None = None,
    filled_quantity: float | None = None,
    avg_fill_price: float | None = None,
    ib_order_id: int | None = None,
) -> OrderEvent:
    event = OrderEvent(
        order_id=order_id,
        event_type=event_type,
        message=message,
        status=status,
        filled_quantity=filled_quantity,
        avg_fill_price=avg_fill_price,
        ib_order_id=ib_order_id,
        created_at=now_utc(),
    )
    session.add(event)
    session.flush()
    return event


def transition_order_status(
    session: Session,
    order: Order,
    next_status: str,
    *,
    message: str,
    event_type: str = "status_change",
) -> OrderEvent:
    if not can_transition_order_status(order.status, next_status):
        raise ValueError(f"Invalid order status transition: {order.status} -> {next_status}")

    now = now_utc()
    order.status = next_status
    order.updated_at = now
    if next_status == ORDER_STATUS_SUBMITTED and order.submitted_at is None:
        order.submitted_at = now
    if next_status in ORDER_TERMINAL_STATUSES:
        order.completed_at = now

    session.flush()
    return append_order_event(
        session=session,
        order_id=order.id,
        event_type=event_type,
        message=message,
        status=next_status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
