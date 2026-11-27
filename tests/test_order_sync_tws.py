"""Broker order identity: permId 0 is "unknown", never a key, and never merges rows."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from ib_async import IB
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Order
from src.services import order_sync_tws
from src.services.intraday_sync_tws import _live_execution_values

CLIENT_ID = 11
OTHER_CLIENT_ID = 12


def _trade(
    *,
    perm_id: int = 0,
    order_id: int = 90000001,
    client_id: int = CLIENT_ID,
    order_ref: str = "",
    status: str = "Submitted",
    quantity: float = 1.0,
) -> Any:
    return SimpleNamespace(
        order=SimpleNamespace(
            action="BUY",
            totalQuantity=quantity,
            orderType="MKT",
            lmtPrice=0.0,
            tif="DAY",
            orderId=order_id,
            permId=perm_id,
            clientId=client_id,
            orderRef=order_ref,
            account="U1234567",
        ),
        orderStatus=SimpleNamespace(status=status, avgFillPrice=0.0),
        contract=SimpleNamespace(
            symbol="CL",
            secType="FUT",
            exchange="NYMEX",
            currency="USD",
            conId=400000001,
            localSymbol="CLZ6",
            tradingClass="CL",
            lastTradeDateOrContractMonth="20261120",
        ),
        filled=lambda: 0.0,
    )


def _apply(session: Session, trade: Any) -> Order:
    return order_sync_tws.apply_trade_to_order(session, trade).order


def _all_orders(session: Session) -> list[Order]:
    return list(session.execute(select(Order).order_by(Order.id)).scalars().all())


def _app_order(session: Session, *, perm_id: int | None = None, source: str = "tradebot") -> Order:
    order = Order(account_id=1, symbol="CL", side="BUY", quantity=1, status="submitted", source=source, ib_perm_id=perm_id)
    session.add(order)
    session.flush()
    return order


def test_perm_id_zero_is_stored_as_null_and_never_merges(db_session: Session) -> None:
    first = _apply(db_session, _trade(perm_id=0, order_id=0))
    second = _apply(db_session, _trade(perm_id=0, order_id=0))

    assert first.id != second.id
    assert first.ib_perm_id is None
    assert second.ib_perm_id is None
    assert len(_all_orders(db_session)) == 2


def test_hand_entered_trades_sharing_order_id_zero_stay_separate(db_session: Session) -> None:
    first = _apply(db_session, _trade(perm_id=0, order_id=0, client_id=0))
    second = _apply(db_session, _trade(perm_id=0, order_id=0, client_id=0, quantity=3.0))

    assert first.id != second.id
    assert len(_all_orders(db_session)) == 2


def test_acknowledged_order_updates_the_row_created_with_perm_id_zero(db_session: Session) -> None:
    first = _apply(db_session, _trade(perm_id=0, order_id=90000001))
    again = _apply(db_session, _trade(perm_id=7777777, order_id=90000001))

    assert again.id == first.id
    assert again.ib_perm_id == 7777777
    assert again.ib_client_id == CLIENT_ID
    assert len(_all_orders(db_session)) == 1


def test_perm_id_match_wins_over_an_order_ref_naming_another_row(db_session: Session) -> None:
    target = _apply(db_session, _trade(perm_id=7777777, order_id=90000001))
    other = _app_order(db_session)

    matched = _apply(db_session, _trade(perm_id=7777777, order_id=90000001, order_ref=f"ngtrader-order-{other.id}"))

    assert matched.id == target.id


def test_order_ref_does_not_match_a_row_with_a_different_perm_id(db_session: Session) -> None:
    owned = _app_order(db_session, perm_id=8888888)

    created = _apply(db_session, _trade(perm_id=7777777, order_id=90000002, order_ref=f"ngtrader-order-{owned.id}"))

    assert created.id != owned.id
    assert owned.ib_perm_id == 8888888


def test_order_ref_matches_an_app_order_whose_perm_id_is_unknown(db_session: Session) -> None:
    owned = _app_order(db_session, perm_id=None)

    matched = _apply(db_session, _trade(perm_id=7777777, order_id=90000002, order_ref=f"ngtrader-order-{owned.id}"))

    assert matched.id == owned.id
    assert matched.ib_perm_id == 7777777


def test_order_ref_does_not_match_a_broker_synced_row(db_session: Session) -> None:
    synced = _app_order(db_session, perm_id=None, source=order_sync_tws.DEFAULT_ORDER_SYNC_SOURCE)

    created = _apply(db_session, _trade(perm_id=0, order_id=90000003, order_ref=f"ngtrader-order-{synced.id}"))

    assert created.id != synced.id


def test_order_id_from_another_client_does_not_match(db_session: Session) -> None:
    first = _apply(db_session, _trade(perm_id=0, order_id=90000001, client_id=CLIENT_ID))
    second = _apply(db_session, _trade(perm_id=0, order_id=90000001, client_id=OTHER_CLIENT_ID))

    assert first.id != second.id


def test_syncing_the_same_batch_twice_leaves_three_rows(db_session: Session) -> None:
    batch = [
        _trade(perm_id=7777777, order_id=90000001),
        _trade(perm_id=8888888, order_id=90000002),
        _trade(perm_id=0, order_id=90000003),
    ]

    for trade in batch:
        _apply(db_session, trade)
    for trade in batch:
        _apply(db_session, trade)

    assert len(_all_orders(db_session)) == 3


def test_live_fill_with_perm_id_zero_stores_null() -> None:
    fill = SimpleNamespace(
        execution=SimpleNamespace(execId="0000abcd.12345678.01.01", permId=0, orderId=90000001, shares=1.0, price=70.0, side="BOT"),
        contract=SimpleNamespace(conId=400000001, symbol="CL", secType="FUT", localSymbol="CLZ6"),
    )
    now = order_sync_tws.now_utc()

    values = _live_execution_values(fill, 1, now, now)

    assert values["ib_perm_id"] is None


def _sync(db_session: Session, monkeypatch: pytest.MonkeyPatch, trades: list[Any]) -> dict[str, Any]:
    monkeypatch.setattr(order_sync_tws, "_collect_recent_trades", lambda ib: trades)
    engine = cast(Engine, db_session.get_bind())
    return order_sync_tws.sync_orders_with_ib(engine, ib=cast(IB, SimpleNamespace()))


def test_sync_returns_created_and_updated_order_ids(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    existing = _apply(db_session, _trade(perm_id=7777771, order_id=90000001, status="Submitted"))
    db_session.flush()

    result = _sync(
        db_session,
        monkeypatch,
        [
            _trade(perm_id=7777771, order_id=90000001, status="Cancelled"),
            _trade(perm_id=7777772, order_id=90000002),
        ],
    )

    created = db_session.execute(select(Order).where(Order.ib_perm_id == 7777772)).scalar_one()
    assert result["created_order_ids"] == [created.id]
    assert result["updated_order_ids"] == [existing.id]
    assert result["created_orders_count"] == 1
    assert result["updated_orders_count"] == 1


def test_sync_with_no_changes_returns_empty_id_lists(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    trades = [_trade(perm_id=7777773, order_id=90000003)]
    _sync(db_session, monkeypatch, trades)

    result = _sync(db_session, monkeypatch, trades)

    assert result["created_order_ids"] == []
    assert result["updated_order_ids"] == []


def test_sync_does_not_publish_in_the_worker_process() -> None:
    assert not hasattr(order_sync_tws, "broadcaster")
