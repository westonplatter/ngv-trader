"""Order worker policy: status mapping and the writes that go through the state machine."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.enums import OrderStatus
from src.models import Account, Order, OrderEvent
from src.services import order_worker
from src.services.order_queue import FORCED_STATUS_CHANGE_EVENT_TYPE

TEST_ACCOUNT = "U1234567"


def _make_order(session: Session, status: str, *, account_id: int = 1) -> Order:
    order = Order(account_id=account_id, symbol="CL", side="BUY", quantity=1, status=status)
    session.add(order)
    session.flush()
    return order


def _events(session: Session, order: Order) -> list[OrderEvent]:
    stmt = select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id)
    return list(session.execute(stmt).scalars().all())


def _fake_trade(ib_status: str, filled: float = 0.0) -> Any:
    return SimpleNamespace(
        orderStatus=SimpleNamespace(status=ib_status, avgFillPrice=0.0),
        order=SimpleNamespace(orderId=0, permId=0),
        contract=SimpleNamespace(conId=0, localSymbol="", tradingClass="", lastTradeDateOrContractMonth=""),
        filled=lambda: filled,
        remaining=lambda: 1.0 - filled,
    )


@pytest.mark.parametrize(
    ("ib_status", "filled", "expected"),
    [
        ("Filled", 1.0, OrderStatus.FILLED),
        ("Rejected", 0.0, OrderStatus.REJECTED),
        ("Cancelled", 0.0, OrderStatus.CANCELLED),
        ("ApiCancelled", 0.0, OrderStatus.CANCELLED),
        ("Inactive", 0.0, OrderStatus.CANCELLED),
        ("Submitted", 0.0, OrderStatus.SUBMITTED),
        ("PreSubmitted", 0.0, OrderStatus.SUBMITTED),
        ("Submitted", 0.5, OrderStatus.PARTIALLY_FILLED),
        ("SomethingNew", 0.0, OrderStatus.SUBMITTED),
        ("", 0.0, OrderStatus.QUEUED),
        (None, 0.0, OrderStatus.QUEUED),
    ],
)
def test_normalize_ib_status_returns_order_status_members(ib_status: str | None, filled: float, expected: OrderStatus) -> None:
    result = order_worker.normalize_ib_status(ib_status, filled)

    assert result is expected


def test_apply_trade_progress_allowed_move_uses_the_caller_event_type(db_session: Session) -> None:
    order = _make_order(db_session, OrderStatus.SUBMITTING)

    changed = order_worker.apply_trade_progress(
        db_session,
        order,
        _fake_trade("Submitted"),
        event_type="order_progress",
        message_prefix="order progress",
    )

    assert changed is True
    assert order.status == OrderStatus.SUBMITTED
    events = _events(db_session, order)
    assert [e.event_type for e in events] == ["order_progress"]


def test_apply_trade_progress_forces_a_disallowed_move_and_records_it(db_session: Session) -> None:
    order = _make_order(db_session, OrderStatus.QUEUED)

    changed = order_worker.apply_trade_progress(
        db_session,
        order,
        _fake_trade("Filled", filled=1.0),
        event_type="order_reconciled",
        message_prefix="startup reconciliation",
    )

    assert changed is True
    assert order.status == OrderStatus.FILLED
    assert order.completed_at is not None
    events = _events(db_session, order)
    assert [e.event_type for e in events] == [FORCED_STATUS_CHANGE_EVENT_TYPE, "order_reconciled"]
    assert "queued -> filled" in events[0].message
    assert all(e.status == OrderStatus.FILLED for e in events)


def test_process_order_without_an_account_fails_through_the_state_machine(db_session: Session) -> None:
    order = _make_order(db_session, OrderStatus.SUBMITTING, account_id=-1)

    order_worker.process_order(SimpleNamespace(), db_session, order, timeout_seconds=1.0)  # type: ignore[arg-type]

    assert order.status == OrderStatus.FAILED
    assert order.last_error == "Missing account row for account_id=-1"
    assert order.completed_at is not None
    events = _events(db_session, order)
    assert [e.event_type for e in events] == ["order_error"]
    assert events[0].message == order.last_error
    assert events[0].status == OrderStatus.FAILED


def test_process_order_fails_closed_while_submission_is_disabled(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    account = Account(account=TEST_ACCOUNT)
    db_session.add(account)
    db_session.flush()
    order = _make_order(db_session, OrderStatus.SUBMITTING, account_id=account.id)
    contract = SimpleNamespace(conId=1, localSymbol="CL", tradingClass="CL", lastTradeDateOrContractMonth="")
    monkeypatch.setattr(order_worker, "get_or_qualify_contract", lambda ib, o: contract)
    ib = SimpleNamespace(managedAccounts=lambda: [TEST_ACCOUNT])

    order_worker.process_order(ib, db_session, order, timeout_seconds=1.0)  # type: ignore[arg-type]

    assert order.status == OrderStatus.FAILED
    assert order.last_error == "Order execution is not supported at this time."
    assert order.completed_at is not None
    events = _events(db_session, order)
    assert [e.event_type for e in events] == ["contract_qualified", "order_error"]
    assert events[-1].message == "Worker error: Order execution is not supported at this time."
