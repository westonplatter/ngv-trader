"""Order response mapping: combo legs and derived option fields."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.api.schemas import load_order_legs, to_order_response
from src.models import ContractRef, Order, OrderLeg


def _order(session: Session, *, sec_type: str, local_symbol: str, perm_id: int) -> Order:
    order = Order(
        account_id=1,
        symbol="MNQ",
        sec_type=sec_type,
        side="BUY",
        quantity=1.5,
        remaining_quantity=1.5,
        exec_role="combo_summary" if sec_type == "BAG" else "standalone",
        status="submitted",
        source="broker_sync",
        local_symbol=local_symbol,
        ib_perm_id=perm_id,
    )
    session.add(order)
    session.flush()
    return order


def test_bag_response_has_no_derived_strike_or_right(db_session: Session) -> None:
    order = _order(db_session, sec_type="BAG", local_symbol="C0707", perm_id=7777791)

    response = to_order_response(order, None)

    assert response.option_right is None
    assert response.option_strike is None
    assert response.quantity == 1.5
    assert response.remaining_quantity == 1.5


def test_option_response_still_derives_strike_and_right(db_session: Session) -> None:
    order = _order(db_session, sec_type="FOP", local_symbol="WA4G6 C0707", perm_id=7777792)

    response = to_order_response(order, None)

    assert response.option_right == "C"
    assert response.option_strike == "0707"


def test_legs_load_in_order_with_names_from_contract_refs(db_session: Session) -> None:
    first = _order(db_session, sec_type="BAG", local_symbol="MNQ", perm_id=7777793)
    second = _order(db_session, sec_type="BAG", local_symbol="MNQ", perm_id=7777794)
    db_session.add(
        ContractRef(
            con_id=400000003,
            symbol="MNQ",
            sec_type="FUT",
            exchange="CME",
            currency="USD",
            local_symbol="MNQZ6",
            contract_expiry="20261218",
            fetched_at=datetime.now(timezone.utc),
        )
    )
    for order in (first, second):
        db_session.add(OrderLeg(order_id=order.id, leg_index=1, con_id=400000004, ratio=2, action="BUY", quantity=2.0))
        db_session.add(OrderLeg(order_id=order.id, leg_index=0, con_id=400000003, ratio=1, action="SELL", quantity=-1.0))
    db_session.flush()

    legs = load_order_legs(db_session, [first, second])
    response = to_order_response(first, None, legs=legs[first.id])

    assert [leg.leg_index for leg in response.legs] == [0, 1]
    assert [leg.quantity for leg in response.legs] == [-1.0, 2.0]
    assert response.legs[0].contract_display_name.startswith("MNQ")
    assert response.legs[1].contract_display_name == "MNQ (con 400000004)"
    assert set(legs) == {first.id, second.id}
