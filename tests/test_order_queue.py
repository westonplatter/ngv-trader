"""Order status state machine: the transition table, forced moves, and stamps."""

from __future__ import annotations

from itertools import product

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.enums import OrderStatus
from src.models import Order, OrderEvent
from src.services.order_queue import (
    ALLOWED_ORDER_STATUS_TRANSITIONS,
    FORCED_STATUS_CHANGE_EVENT_TYPE,
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_SUBMITTING,
    ORDER_TERMINAL_STATUSES,
    can_transition_order_status,
    transition_order_status,
)

ALLOWED_PAIRS = [(src, dst) for src, targets in ALLOWED_ORDER_STATUS_TRANSITIONS.items() for dst in targets]
DISALLOWED_PAIRS = [(src, dst) for src, dst in product(OrderStatus, OrderStatus) if dst not in ALLOWED_ORDER_STATUS_TRANSITIONS[src]]


def _make_order(session: Session, status: str) -> Order:
    order = Order(account_id=1, symbol="CL", side="BUY", quantity=1, status=status)
    session.add(order)
    session.flush()
    return order


def _events(session: Session, order: Order) -> list[OrderEvent]:
    stmt = select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id)
    return list(session.execute(stmt).scalars().all())


def test_every_status_has_a_table_entry() -> None:
    assert set(ALLOWED_ORDER_STATUS_TRANSITIONS) == set(OrderStatus)
    assert ALLOWED_PAIRS, "the table must allow at least one transition"
    assert DISALLOWED_PAIRS, "the table must forbid at least one transition"


@pytest.mark.parametrize(("src", "dst"), ALLOWED_PAIRS)
def test_allowed_transition_applies_and_records_event(db_session: Session, src: OrderStatus, dst: OrderStatus) -> None:
    order = _make_order(db_session, src)
    assert can_transition_order_status(src, dst)

    event = transition_order_status(db_session, order, dst, message="moving")

    assert order.status == dst
    assert event.event_type == "status_change"
    assert event.status == dst
    assert event.message == "moving"
    assert _events(db_session, order) == [event]


@pytest.mark.parametrize(("src", "dst"), DISALLOWED_PAIRS)
def test_disallowed_transition_raises_and_changes_nothing(db_session: Session, src: OrderStatus, dst: OrderStatus) -> None:
    order = _make_order(db_session, src)
    assert not can_transition_order_status(src, dst)

    with pytest.raises(ValueError, match="Invalid order status transition"):
        transition_order_status(db_session, order, dst, message="nope")

    assert order.status == src
    assert order.completed_at is None
    assert _events(db_session, order) == []


def test_unknown_current_status_cannot_transition() -> None:
    assert not can_transition_order_status("bogus", ORDER_STATUS_SUBMITTED)


def test_forced_disallowed_transition_applies_and_records_forced_event(db_session: Session) -> None:
    order = _make_order(db_session, ORDER_STATUS_QUEUED)
    assert not can_transition_order_status(ORDER_STATUS_QUEUED, OrderStatus.FILLED)

    event = transition_order_status(
        db_session,
        order,
        OrderStatus.FILLED,
        message="broker says filled",
        event_type="order_reconciled",
        force=True,
    )

    assert order.status == OrderStatus.FILLED
    assert order.completed_at is not None
    assert event.event_type == FORCED_STATUS_CHANGE_EVENT_TYPE == "forced_status_change"
    assert event.status == OrderStatus.FILLED
    assert "queued -> filled" in event.message
    assert "broker says filled" in event.message
    assert _events(db_session, order) == [event]


def test_forced_but_allowed_transition_records_the_normal_event(db_session: Session) -> None:
    order = _make_order(db_session, ORDER_STATUS_QUEUED)

    event = transition_order_status(
        db_session,
        order,
        ORDER_STATUS_SUBMITTING,
        message="claimed",
        event_type="order_submitting",
        force=True,
    )

    assert order.status == ORDER_STATUS_SUBMITTING
    assert event.event_type == "order_submitting"
    assert event.message == "claimed"


def test_forced_move_out_of_a_terminal_status_keeps_completed_at(db_session: Session) -> None:
    order = _make_order(db_session, ORDER_STATUS_SUBMITTED)
    transition_order_status(db_session, order, OrderStatus.CANCELLED, message="cancelled")
    stamped = order.completed_at
    assert stamped is not None

    transition_order_status(db_session, order, OrderStatus.REJECTED, message="late reject", force=True)

    assert order.status == OrderStatus.REJECTED
    assert order.completed_at == stamped


@pytest.mark.parametrize("terminal", sorted(ORDER_TERMINAL_STATUSES))
def test_terminal_status_stamps_completed_at(db_session: Session, terminal: OrderStatus) -> None:
    order = _make_order(db_session, ORDER_STATUS_SUBMITTED)
    assert order.completed_at is None

    transition_order_status(db_session, order, terminal, message="done")

    assert order.completed_at is not None
    assert order.updated_at is not None


@pytest.mark.parametrize(
    ("src", "live"),
    [
        (OrderStatus.QUEUED, OrderStatus.SUBMITTING),
        (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.RECONCILE_REQUIRED),
    ],
)
def test_non_terminal_status_leaves_completed_at_unset(db_session: Session, src: OrderStatus, live: OrderStatus) -> None:
    order = _make_order(db_session, src)

    transition_order_status(db_session, order, live, message="working")

    assert order.completed_at is None


def test_submitted_stamps_submitted_at_once(db_session: Session) -> None:
    order = _make_order(db_session, ORDER_STATUS_SUBMITTING)
    assert order.submitted_at is None

    transition_order_status(db_session, order, ORDER_STATUS_SUBMITTED, message="acked")
    first = order.submitted_at
    assert first is not None

    transition_order_status(db_session, order, OrderStatus.RECONCILE_REQUIRED, message="lost")
    transition_order_status(db_session, order, ORDER_STATUS_SUBMITTED, message="found again")

    assert order.submitted_at == first
