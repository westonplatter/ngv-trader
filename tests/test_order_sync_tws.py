"""Broker order identity: permId 0 is "unknown", never a key, and never merges rows."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ib_async import IB
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import ContractRef, Job, Order, OrderEvent, OrderLeg
from src.services import order_sync_tws
from src.services.intraday_sync_tws import _live_execution_values
from src.services.jobs import JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT

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
    monkeypatch.setattr(order_sync_tws, "_collect_recent_trades", lambda ib: order_sync_tws.TradeFetch(trades=trades, ok=True))
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


def _working_order(db_session: Session, *, perm_id: int, status: str = "submitted") -> Order:
    order = _apply(db_session, _trade(perm_id=perm_id, order_id=90000000 + perm_id % 1000))
    order.status = status
    db_session.flush()
    return order


def test_successful_fetch_omitting_a_working_order_marks_it_reconcile_required(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    gone = _working_order(db_session, perm_id=7777781)
    kept = _working_order(db_session, perm_id=7777782)

    result = _sync(db_session, monkeypatch, [_trade(perm_id=7777782, order_id=90000782)])

    db_session.refresh(gone)
    db_session.refresh(kept)
    assert gone.status == "reconcile_required"
    assert kept.status == "submitted"
    assert result["updated_order_ids"] == [gone.id]
    events = db_session.execute(select(OrderEvent).where(OrderEvent.order_id == gone.id)).scalars().all()
    assert any(event.status == "reconcile_required" for event in events)


def test_partially_filled_order_missing_from_fetch_is_swept(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _working_order(db_session, perm_id=7777783, status="partially_filled")

    _sync(db_session, monkeypatch, [])

    db_session.refresh(order)
    assert order.status == "reconcile_required"


def test_empty_book_sweeps_every_working_order(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    orders = [_working_order(db_session, perm_id=7777784), _working_order(db_session, perm_id=7777785)]

    result = _sync(db_session, monkeypatch, [])

    for order in orders:
        db_session.refresh(order)
        assert order.status == "reconcile_required"
    assert sorted(result["updated_order_ids"]) == sorted(order.id for order in orders)


def test_failed_fetch_leaves_every_order_unchanged(db_session: Session) -> None:
    order = _working_order(db_session, perm_id=7777786)

    def fail() -> list[Any]:
        raise RuntimeError("TWS refused")

    fake_ib = SimpleNamespace(
        reqOpenOrders=lambda: None,
        waitOnUpdate=lambda timeout=None: None,
        openTrades=lambda: [],
        reqAllOpenOrders=fail,
        reqCompletedOrders=lambda apiOnly=False: [],
    )
    result = order_sync_tws.sync_orders_with_ib(cast(Engine, db_session.get_bind()), ib=cast(IB, fake_ib))

    db_session.refresh(order)
    assert order.status == "submitted"
    assert result["updated_order_ids"] == []


def test_failed_fetch_still_applies_the_trades_it_gathered(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _working_order(db_session, perm_id=7777787)
    monkeypatch.setattr(
        order_sync_tws,
        "_collect_recent_trades",
        lambda ib: order_sync_tws.TradeFetch(trades=[_trade(perm_id=7777787, order_id=90000787, status="Cancelled")], ok=False),
    )

    order_sync_tws.sync_orders_with_ib(cast(Engine, db_session.get_bind()), ib=cast(IB, SimpleNamespace()))

    db_session.refresh(order)
    assert order.status == "cancelled"


def test_swept_order_seen_again_returns_to_submitted(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _working_order(db_session, perm_id=7777788)
    _sync(db_session, monkeypatch, [])
    db_session.refresh(order)
    assert order.status == "reconcile_required"

    result = _sync(db_session, monkeypatch, [_trade(perm_id=7777788, order_id=90000788)])

    db_session.refresh(order)
    assert order.status == "submitted"
    assert result["updated_order_ids"] == [order.id]


def test_queued_order_is_never_swept(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _app_order(db_session)
    order.status = "queued"
    db_session.flush()

    _sync(db_session, monkeypatch, [])

    db_session.refresh(order)
    assert order.status == "queued"


def test_order_written_during_the_fetch_is_not_swept(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Order] = []

    def fetch(ib: Any) -> order_sync_tws.TradeFetch:
        created.append(_app_order(db_session))
        return order_sync_tws.TradeFetch(trades=[], ok=True)

    monkeypatch.setattr(order_sync_tws, "_collect_recent_trades", fetch)
    order_sync_tws.sync_orders_with_ib(cast(Engine, db_session.get_bind()), ib=cast(IB, SimpleNamespace()))

    db_session.refresh(created[0])
    assert created[0].status == "submitted"


def test_observed_order_records_last_seen_at(db_session: Session) -> None:
    order = _apply(db_session, _trade(perm_id=7777789, order_id=90000789))

    assert order.last_seen_at is not None


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tws_orders"
FIXTURE_ORDER_IDS = {-9000000001: -1, -9000000002: -2, -9000000003: -3}


def _combo_trade(
    *,
    action: str = "BUY",
    quantity: float = 1.0,
    perm_id: int = 8888888,
    order_id: int = -2,
    filled: float = 0.0,
    legs: list[tuple[int, int, str]] | None = None,
    status: str = "Submitted",
) -> Any:
    leg_rows = legs if legs is not None else [(400000003, 1, "SELL"), (400000004, 1, "BUY")]
    return SimpleNamespace(
        order=SimpleNamespace(
            action=action,
            totalQuantity=quantity,
            orderType="LMT",
            lmtPrice=29.0,
            tif="DAY",
            orderId=order_id,
            permId=perm_id,
            clientId=0,
            orderRef="",
            account="U1234567",
        ),
        orderStatus=SimpleNamespace(status=status, avgFillPrice=0.0),
        contract=SimpleNamespace(
            symbol="MNQ",
            secType="BAG",
            exchange="CME",
            currency="USD",
            conId=400000002,
            localSymbol="MNQ",
            tradingClass="",
            lastTradeDateOrContractMonth="",
            comboLegs=[SimpleNamespace(conId=con_id, ratio=ratio, action=leg_action, exchange="CME", openClose=0) for con_id, ratio, leg_action in leg_rows],
        ),
        filled=lambda: filled,
    )


def _fixture_trade(raw: dict[str, Any]) -> Any:
    contract, order, status = raw["contract"], raw["order"], raw["orderStatus"]
    return SimpleNamespace(
        order=SimpleNamespace(**{**order, "orderId": FIXTURE_ORDER_IDS.get(order["orderId"], -1)}),
        orderStatus=SimpleNamespace(**status),
        contract=SimpleNamespace(**{**contract, "comboLegs": [SimpleNamespace(**leg) for leg in contract["comboLegs"]]}),
        filled=lambda: status["filled"],
    )


def _legs(session: Session, order: Order) -> list[OrderLeg]:
    return list(session.execute(select(OrderLeg).where(OrderLeg.order_id == order.id).order_by(OrderLeg.leg_index)).scalars().all())


def _fixture_spreads() -> dict[int, dict[str, Any]]:
    events = json.loads((FIXTURES / "events_client0_autoopen.json").read_text())["events"]
    return {event["order"]["permId"]: event for event in events if event["contract"]["secType"] == "BAG"}


def test_fixture_spreads_make_one_parent_and_one_leg_per_combo_leg(db_session: Session) -> None:
    for perm_id, event in _fixture_spreads().items():
        order = _apply(db_session, _fixture_trade(event))
        legs = _legs(db_session, order)

        assert order.ib_perm_id == perm_id
        assert order.exec_role == "combo_summary"
        assert [leg.con_id for leg in legs] == [leg["conId"] for leg in event["contract"]["comboLegs"]]
    assert len(_all_orders(db_session)) == len(_fixture_spreads())


def test_buy_and_sell_spreads_sign_legs_by_leg_and_parent_action(db_session: Session) -> None:
    spreads = _fixture_spreads()
    buy = _apply(db_session, _fixture_trade(spreads[8888888]))
    sell = _apply(db_session, _fixture_trade(spreads[9999999]))

    assert buy.side == "BUY"
    assert [leg.action for leg in _legs(db_session, buy)] == ["SELL", "BUY"]
    assert [leg.quantity for leg in _legs(db_session, buy)] == [-1.0, 1.0]
    assert sell.side == "SELL"
    assert [leg.action for leg in _legs(db_session, sell)] == ["SELL", "BUY"]
    assert [leg.quantity for leg in _legs(db_session, sell)] == [1.0, -1.0]


def test_snapshot_trades_apply_with_legs_matching_their_combo_legs(db_session: Session) -> None:
    snapshot = json.loads((FIXTURES / "snapshot_client0.json").read_text())["snapshot"]
    raws = [raw for group in snapshot.values() for raw in group]
    seen: set[int] = set()
    for raw in raws:
        perm_id = raw["order"]["permId"]
        if perm_id in seen:
            continue
        seen.add(perm_id)
        trade = _fixture_trade(raw)
        order = _apply(db_session, trade)
        assert len(_legs(db_session, order)) == len(raw["contract"]["comboLegs"])


def test_ratio_one_by_two_spread_of_three_gives_legs_three_and_six(db_session: Session) -> None:
    order = _apply(db_session, _combo_trade(quantity=3.0, legs=[(400000003, 1, "BUY"), (400000004, 2, "SELL")]))

    assert [leg.quantity for leg in _legs(db_session, order)] == [3.0, -6.0]
    assert [leg.ratio for leg in _legs(db_session, order)] == [1, 2]


def test_fractional_total_quantity_is_stored_as_given(db_session: Session) -> None:
    order = _apply(db_session, _trade(perm_id=7777781, order_id=90000781, quantity=0.5))

    assert order.quantity == 0.5
    assert order.remaining_quantity == 0.5


def test_partial_fill_sets_remaining_to_quantity_minus_filled(db_session: Session) -> None:
    trade = _trade(perm_id=7777782, order_id=90000782, quantity=5.0)
    trade.filled = lambda: 2.0
    order = _apply(db_session, trade)

    assert order.remaining_quantity == 3.0
    assert order.filled_quantity == 2.0


def test_reapplying_the_same_combo_updates_legs_without_duplicates(db_session: Session) -> None:
    first = _apply(db_session, _combo_trade(quantity=1.0))
    second = order_sync_tws.apply_trade_to_order(db_session, _combo_trade(quantity=2.0))

    assert second.order.id == first.id
    assert second.changed
    assert [leg.quantity for leg in _legs(db_session, first)] == [-2.0, 2.0]
    assert not order_sync_tws.apply_trade_to_order(db_session, _combo_trade(quantity=2.0)).changed


def test_plain_order_is_standalone_with_no_legs(db_session: Session) -> None:
    order = _apply(db_session, _trade(perm_id=7777783, order_id=90000783))

    assert order.exec_role == "standalone"
    assert _legs(db_session, order) == []


def test_unknown_leg_contracts_enqueue_a_qualify_job_and_known_ones_fill_display_fields(db_session: Session) -> None:
    db_session.add(
        ContractRef(
            con_id=400000003,
            symbol="MNQ",
            sec_type="FUT",
            exchange="CME",
            currency="USD",
            local_symbol="MNQZ6",
            contract_expiry="20261218",
            fetched_at=order_sync_tws.now_utc(),
        )
    )
    db_session.flush()
    order = _apply(db_session, _combo_trade())

    jobs = list(db_session.execute(select(Job).where(Job.job_type == JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT)).scalars().all())
    assert [job.payload for job in jobs] == [{"con_ids": [400000004]}]
    assert [leg.local_symbol for leg in _legs(db_session, order)] == ["MNQZ6", None]


def test_reapplying_a_combo_does_not_requeue_the_qualify_job(db_session: Session) -> None:
    _apply(db_session, _combo_trade())
    for job in db_session.execute(select(Job).where(Job.job_type == JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT)).scalars():
        job.status = "failed"
    db_session.flush()

    _apply(db_session, _combo_trade())

    jobs = list(db_session.execute(select(Job).where(Job.job_type == JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT)).scalars().all())
    assert len(jobs) == 1
