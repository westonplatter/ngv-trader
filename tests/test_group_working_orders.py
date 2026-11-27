"""Working orders shown under the trade groups that hold their contracts."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import Account, Order, OrderLeg, TradeGroup
from src.services.group_working_orders import working_orders_for_group
from tests.trade_group_factories import (
    ACCOUNT_LSC,
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
)

API = "/api/v1"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _order(session: Session, account: Account, *, con_id: int | None, status: str = "submitted", legs: list[int] | None = None) -> Order:
    order = Order(
        account_id=account.id,
        symbol="CL",
        sec_type="BAG" if legs else "FUT",
        side="BUY",
        quantity=1,
        status=status,
        source="broker_sync",
        con_id=con_id,
    )
    session.add(order)
    session.flush()
    for index, leg_con_id in enumerate(legs or []):
        session.add(OrderLeg(order_id=order.id, leg_index=index, con_id=leg_con_id, ratio=1, action="BUY", quantity=1.0))
    session.flush()
    return order


def _hold(session: Session, group: TradeGroup, account: Account, con_id: int, seq: int, quantity: float = 1.0) -> None:
    side = "BUY" if quantity > 0 else "SELL"
    make_execution(session, group=group, account=account, con_id=con_id, exec_id=make_exec_id(seq), side=side, quantity=quantity)


def _ids(session: Session, group: TradeGroup) -> list[int]:
    return [match.order.id for match in working_orders_for_group(session, group.id)]


def test_working_order_on_a_held_contract_shows_under_the_group(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL carry")
    _hold(db_session, group, account, CON_CL, 1)
    held = _order(db_session, account, con_id=CON_CL)
    _order(db_session, account, con_id=CON_NG)

    matches = working_orders_for_group(db_session, group.id)

    assert [(m.order.id, m.matched_con_ids, m.shared_with_group_ids) for m in matches] == [(held.id, [CON_CL], [])]


def test_combo_matches_when_any_leg_is_held(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL roll")
    _hold(db_session, group, account, CON_CL, 1)
    roll = _order(db_session, account, con_id=None, legs=[CON_CL, CON_NG])

    matches = working_orders_for_group(db_session, group.id)

    assert [(m.order.id, m.matched_con_ids) for m in matches] == [(roll.id, [CON_CL])]


def test_terminal_orders_are_excluded_and_reconcile_required_is_kept(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL carry")
    _hold(db_session, group, account, CON_CL, 1)
    for status in ("filled", "cancelled", "rejected", "queued"):
        _order(db_session, account, con_id=CON_CL, status=status)
    partial = _order(db_session, account, con_id=CON_CL, status="partially_filled")
    unknown = _order(db_session, account, con_id=CON_CL, status="reconcile_required")

    assert sorted(_ids(db_session, group)) == sorted([partial.id, unknown.id])


def test_closed_position_and_other_account_do_not_match(db_session: Session) -> None:
    account = make_account(db_session)
    other_account = make_account(db_session, ACCOUNT_LSC, alias="lsc")
    group = make_group(db_session, "CL carry")
    _hold(db_session, group, account, CON_ES, 1)
    _hold(db_session, group, account, CON_ES, 2, quantity=-1.0)
    _hold(db_session, group, account, CON_CL, 3)
    _order(db_session, account, con_id=CON_ES)
    _order(db_session, other_account, con_id=CON_CL)

    assert _ids(db_session, group) == []


def test_unsettled_tagged_fill_counts_as_held(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "NG today")
    make_live_execution(db_session, account=account, con_id=CON_NG, exec_id=make_exec_id(9), group=group)
    order = _order(db_session, account, con_id=CON_NG)

    assert _ids(db_session, group) == [order.id]


def test_contract_held_by_two_groups_is_marked_shared(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    first = make_group(db_session, "CL carry")
    second = make_group(db_session, "CL hedge")
    _hold(db_session, first, account, CON_CL, 1)
    _hold(db_session, second, account, CON_CL, 2)
    order = _order(db_session, account, con_id=CON_CL)

    body = client.get(f"{API}/trade-groups/{first.id}/working-orders").json()

    assert [(item["order"]["id"], item["matched_con_ids"], item["shared_with"]) for item in body] == [
        (order.id, [CON_CL], [{"id": second.id, "name": "CL hedge"}])
    ]


def test_group_with_no_open_positions_returns_empty(client: TestClient, db_session: Session) -> None:
    group = make_group(db_session, "empty")

    assert client.get(f"{API}/trade-groups/{group.id}/working-orders").json() == []
    assert client.get(f"{API}/trade-groups/999999/working-orders").status_code == 404
