"""Order queue domain primitives.

This module intentionally contains no broker I/O. It only provides shared order
state and event helpers used by API/worker layers.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.domain.enums import OrderStatus
from src.models import Order, OrderEvent
from src.utils.time import now_utc

ORDER_STATUS_QUEUED = OrderStatus.QUEUED
ORDER_STATUS_SUBMITTING = OrderStatus.SUBMITTING
ORDER_STATUS_SUBMITTED = OrderStatus.SUBMITTED
ORDER_STATUS_PARTIALLY_FILLED = OrderStatus.PARTIALLY_FILLED
ORDER_STATUS_FILLED = OrderStatus.FILLED
ORDER_STATUS_CANCELLED = OrderStatus.CANCELLED
ORDER_STATUS_REJECTED = OrderStatus.REJECTED
ORDER_STATUS_FAILED = OrderStatus.FAILED
ORDER_STATUS_RECONCILE_REQUIRED = OrderStatus.RECONCILE_REQUIRED

ORDER_TERMINAL_STATUSES = {
    ORDER_STATUS_FILLED,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_FAILED,
}

FORCED_STATUS_CHANGE_EVENT_TYPE = "forced_status_change"

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


def can_transition_order_status(current_status: str, next_status: str) -> bool:
    allowed = ALLOWED_ORDER_STATUS_TRANSITIONS.get(current_status)
    if allowed is None:
        return False
    return next_status in allowed


def append_order_event(  # noqa: PLR0913 — public event-append signature used by callers
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
    force: bool = False,
) -> OrderEvent:
    """Move ``order`` to ``next_status`` and record the event.

    A transition the table does not allow raises ``ValueError``. With
    ``force=True`` it is applied anyway, for callers that must follow the
    broker's reported state (reconciliation); the event is then recorded as
    ``forced_status_change`` with the from/to statuses and ``message``.
    """
    allowed = can_transition_order_status(order.status, next_status)
    if not allowed and not force:
        raise ValueError(f"Invalid order status transition: {order.status} -> {next_status}")
    if not allowed:
        event_type = FORCED_STATUS_CHANGE_EVENT_TYPE
        message = f"Forced status change {order.status} -> {next_status}: {message}"

    now = now_utc()
    order.status = next_status
    order.updated_at = now
    if next_status == ORDER_STATUS_SUBMITTED and order.submitted_at is None:
        order.submitted_at = now
    if next_status in ORDER_TERMINAL_STATUSES and order.completed_at is None:
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
