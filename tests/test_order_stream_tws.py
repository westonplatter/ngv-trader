"""Order stream: handlers, coalescing writer, reconcile, fill-sync follow-up, and the read-only guard."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Job, Order, OrderEvent
from src.services import order_stream_tws, order_sync_tws
from src.services.jobs import (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_INTRADAY_SYNC_TWS,
    enqueue_job_if_idle,
)
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_RECONCILE_REQUIRED,
    ORDER_STATUS_SUBMITTED,
)
from src.services.order_stream_tws import OrderStreamCore, StreamState
from src.services.order_sync_tws import TradeFetch

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "tws_orders"
FIXTURE_ORDER_IDS = {-9000000001: -1, -9000000002: -2, -9000000003: -3}


def _trade(
    *,
    perm_id: int = 7777777,
    order_id: int = -1,
    client_id: int = 0,
    status: str = "Submitted",
    filled: float = 0.0,
    quantity: float = 3.0,
    price: float = 2500.0,
) -> Any:
    return SimpleNamespace(
        order=SimpleNamespace(
            action="BUY",
            totalQuantity=quantity,
            orderType="LMT",
            lmtPrice=price,
            tif="GTC",
            orderId=order_id,
            permId=perm_id,
            clientId=client_id,
            orderRef="",
            account="U1234567",
        ),
        orderStatus=SimpleNamespace(status=status, avgFillPrice=2500.0 if filled else 0.0),
        contract=SimpleNamespace(
            symbol="MNQ",
            secType="FUT",
            exchange="CME",
            currency="USD",
            conId=400000001,
            localSymbol="MNQZ6",
            tradingClass="MNQ",
            lastTradeDateOrContractMonth="20261218",
        ),
        filled=lambda: filled,
    )


def _fixture_trades() -> list[Any]:
    payload = json.loads((FIXTURES / "events_client0_autoopen.json").read_text())
    trades = []
    for event in payload["events"]:
        order = event["order"]
        status = event["orderStatus"]
        trades.append(
            _trade(
                perm_id=order["permId"],
                order_id=FIXTURE_ORDER_IDS[order["orderId"]],
                client_id=order["clientId"],
                status=status["status"],
                filled=status["filled"],
                quantity=order["totalQuantity"],
                price=order["lmtPrice"],
            )
        )
    return trades


def _engine(db_session: Session) -> Engine:
    return cast(Engine, db_session.get_bind())


class Notes:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def __call__(self, order_id: int, event: str) -> None:
        self.calls.append((order_id, event))


def _core(db_session: Session, notes: Notes | None = None) -> tuple[OrderStreamCore, Notes]:
    notes = notes or Notes()
    return OrderStreamCore(_engine(db_session), notify=notes), notes


def _go_live(core: OrderStreamCore) -> None:
    async def fetch() -> TradeFetch:
        return TradeFetch(trades=[], ok=True)

    assert asyncio.run(core.reconcile(fetch)) is True


def _orders(session: Session) -> list[Order]:
    session.expire_all()
    return list(session.execute(select(Order).order_by(Order.id)).scalars().all())


def _event_statuses(session: Session, order_id: int) -> list[str | None]:
    rows = session.execute(select(OrderEvent).where(OrderEvent.order_id == order_id).order_by(OrderEvent.id)).scalars().all()
    return [row.status for row in rows]


def _feed(core: OrderStreamCore, *trades: Any) -> None:
    for trade in trades:
        core.on_order_event(trade)


def _flush(core: OrderStreamCore) -> None:
    asyncio.run(core.flush())


def test_new_to_cancelled_with_a_partial_fill_ends_as_one_cancelled_row(db_session: Session) -> None:
    core, notes = _core(db_session)
    _go_live(core)

    for trade in (
        _trade(perm_id=0, order_id=41, client_id=7, status="PendingSubmit"),
        _trade(perm_id=7777777, order_id=41, client_id=7, status="Submitted"),
        _trade(perm_id=7777777, order_id=41, client_id=7, status="Submitted", filled=1.0),
        _trade(perm_id=7777777, order_id=41, client_id=7, status="Cancelled", filled=1.0),
    ):
        _feed(core, trade)
        _flush(core)

    rows = _orders(db_session)
    assert len(rows) == 1
    assert rows[0].status == ORDER_STATUS_CANCELLED
    assert rows[0].filled_quantity == 1.0
    assert rows[0].ib_perm_id == 7777777
    assert notes.calls[0] == (rows[0].id, "order.created")
    assert all(event == "order.updated" for _, event in notes.calls[1:])


def test_hand_entered_order_with_a_perm_id_from_the_first_event_ends_cancelled(db_session: Session) -> None:
    core, _ = _core(db_session)
    _go_live(core)
    first_order = [t for t in _fixture_trades() if t.order.permId == 7777777]

    for trade in first_order:
        _feed(core, trade)
        _flush(core)

    rows = _orders(db_session)
    assert len(rows) == 1
    assert rows[0].status == ORDER_STATUS_CANCELLED
    assert rows[0].limit_price == 2511.0


def test_opening_inactive_then_submitted_pair_never_creates_a_cancelled_row(db_session: Session) -> None:
    core, notes = _core(db_session)
    _go_live(core)
    opening = _fixture_trades()[:4]

    _feed(core, *opening[:2])
    _flush(core)
    assert _orders(db_session) == []
    assert notes.calls == []

    _feed(core, *opening[2:])
    _flush(core)

    rows = _orders(db_session)
    assert len(rows) == 1
    assert rows[0].status == ORDER_STATUS_SUBMITTED
    assert ORDER_STATUS_CANCELLED not in _event_statuses(db_session, rows[0].id)
    assert notes.calls == [(rows[0].id, "order.created")]


def test_inactive_with_nothing_filled_still_cancels_an_order_that_was_already_known(db_session: Session) -> None:
    core, _ = _core(db_session)
    _go_live(core)
    _feed(core, _trade(status="Submitted"))
    _flush(core)

    _feed(core, _trade(status="Inactive"))
    _flush(core)

    assert _orders(db_session)[0].status == ORDER_STATUS_CANCELLED


def test_five_status_events_inside_one_window_cause_one_write_and_one_notify(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    core, notes = _core(db_session)
    _go_live(core)
    applied: list[Any] = []
    real_apply = order_stream_tws.apply_trade_to_order

    def counting_apply(session: Session, trade: Any) -> Any:
        applied.append(trade)
        return real_apply(session, trade)

    monkeypatch.setattr(order_stream_tws, "apply_trade_to_order", counting_apply)

    _feed(core, *[_trade(price=2500.0 + step) for step in range(5)])
    _flush(core)

    assert len(applied) == 1
    assert len(notes.calls) == 1
    rows = _orders(db_session)
    assert len(rows) == 1
    assert rows[0].limit_price == 2504.0


def test_events_queued_while_reconciling_apply_after_the_sweep(db_session: Session) -> None:
    resting = order_sync_tws.apply_trade_to_order(db_session, _trade(perm_id=7777777, order_id=-1)).order
    gone = order_sync_tws.apply_trade_to_order(db_session, _trade(perm_id=8888888, order_id=-2)).order
    db_session.flush()
    core, notes = _core(db_session)

    async def fetch() -> TradeFetch:
        core.on_order_event(_trade(perm_id=7777777, order_id=-1, status="Cancelled"))
        return TradeFetch(trades=[_trade(perm_id=7777777, order_id=-1, status="Submitted")], ok=True)

    assert asyncio.run(core.reconcile(fetch)) is True
    assert core.state is StreamState.LIVE
    _flush(core)

    db_session.expire_all()
    assert resting.status == ORDER_STATUS_CANCELLED
    assert "reconcile_required" not in _event_statuses(db_session, resting.id)
    assert gone.status == ORDER_STATUS_RECONCILE_REQUIRED
    assert (resting.id, "order.updated") in notes.calls


def test_a_failed_fetch_does_not_sweep_and_does_not_enter_live(db_session: Session) -> None:
    working = order_sync_tws.apply_trade_to_order(db_session, _trade()).order
    db_session.flush()
    core, notes = _core(db_session)

    async def fetch() -> TradeFetch:
        return TradeFetch(trades=[], ok=False)

    assert asyncio.run(core.reconcile(fetch)) is False
    assert core.state is not StreamState.LIVE
    db_session.expire_all()
    assert working.status == ORDER_STATUS_SUBMITTED
    assert notes.calls == []

    core.on_order_event(_trade(status="Cancelled"))
    _flush(core)
    db_session.expire_all()
    assert working.status == ORDER_STATUS_SUBMITTED


def test_a_write_failure_asks_for_a_resync_instead_of_losing_events(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    core, notes = _core(db_session)
    _go_live(core)

    def boom(session: Session, trade: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(order_stream_tws, "apply_trade_to_order", boom)
    _feed(core, _trade())
    _flush(core)

    assert core.resync_requested is True
    assert notes.calls == []


def _jobs(session: Session) -> list[Job]:
    session.expire_all()
    return list(session.execute(select(Job).where(Job.job_type == JOB_TYPE_INTRADAY_SYNC_TWS).order_by(Job.id)).scalars().all())


def _exec(core: OrderStreamCore) -> None:
    core.on_exec_details(_trade(), SimpleNamespace())
    asyncio.run(core.service_fill_sync())


def test_exec_details_enqueues_one_intraday_run_while_one_is_already_queued(db_session: Session) -> None:
    core, _ = _core(db_session)

    _exec(core)
    _exec(core)
    _exec(core)

    jobs = _jobs(db_session)
    assert len(jobs) == 1
    assert jobs[0].status == JOB_STATUS_QUEUED


def test_exec_details_during_a_running_job_causes_exactly_one_follow_up_after_it_finishes(db_session: Session) -> None:
    running = enqueue_job_if_idle(db_session, JOB_TYPE_INTRADAY_SYNC_TWS, {}, "test", None)
    assert running is not None
    running.status = JOB_STATUS_RUNNING
    db_session.flush()
    core, _ = _core(db_session)

    _exec(core)
    _exec(core)
    assert len(_jobs(db_session)) == 1

    running.status = JOB_STATUS_COMPLETED
    db_session.flush()
    asyncio.run(core.service_fill_sync())
    asyncio.run(core.service_fill_sync())

    jobs = _jobs(db_session)
    assert [job.status for job in jobs] == [JOB_STATUS_COMPLETED, JOB_STATUS_QUEUED]


def test_poll_and_stream_inserting_the_same_new_order_leave_one_row(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    order_sync_tws.apply_trade_to_order(db_session, _trade(perm_id=7777777, order_id=-1, status="Submitted", price=2500.0))
    db_session.flush()
    real_find = order_sync_tws._find_matching_order
    calls = {"n": 0}

    def stale_find(session: Session, trade: Any) -> Order | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(session, trade)

    monkeypatch.setattr(order_sync_tws, "_find_matching_order", stale_find)

    result = order_sync_tws.apply_trade_to_order(db_session, _trade(perm_id=7777777, order_id=-1, status="Cancelled", price=2511.0))

    rows = _orders(db_session)
    assert len(rows) == 1
    assert result.created is False
    assert result.order.id == rows[0].id
    assert rows[0].status == ORDER_STATUS_CANCELLED
    assert rows[0].limit_price == 2511.0


def test_heartbeat_details_carry_state_and_last_event_time(db_session: Session) -> None:
    core, _ = _core(db_session)
    assert json.loads(core.heartbeat_details())["last_event_at"] is None

    core.on_order_event(_trade())
    details = json.loads(core.heartbeat_details())

    assert details["state"] == core.state.value
    assert details["last_event_at"] is not None


def _load_script() -> ModuleType:
    path = REPO_ROOT / "scripts" / "work_order_stream.py"
    spec = importlib.util.spec_from_file_location("work_order_stream_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_process_exits_without_connecting_when_the_flag_is_unset(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("ORDER_STREAM_ENABLED", raising=False)
    script = _load_script()

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("must not connect or touch the database")

    monkeypatch.setattr(script, "load_env", lambda env_name: None)
    monkeypatch.setattr(script, "get_engine", forbidden)
    monkeypatch.setattr(script, "run_order_stream", forbidden)
    monkeypatch.setattr("sys.argv", ["work_order_stream.py", "--env", "dev"])
    logging.getLogger("worker:order-stream").disabled = False

    with caplog.at_level("INFO"):
        assert script.main() == 0

    assert "ORDER_STREAM_ENABLED" in caplog.text


def test_enable_flag_and_client_id_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ORDER_STREAM_ENABLED", raising=False)
    monkeypatch.delenv("ORDER_STREAM_CLIENT_ID", raising=False)
    assert order_stream_tws.order_stream_enabled() is False
    assert order_stream_tws.order_stream_client_id() == 0

    monkeypatch.setenv("ORDER_STREAM_ENABLED", "true")
    monkeypatch.setenv("ORDER_STREAM_CLIENT_ID", "9")
    assert order_stream_tws.order_stream_enabled() is True
    assert order_stream_tws.order_stream_client_id() == 9


FORBIDDEN_BROKER_CALLS = {"placeOrder", "cancelOrder", "reqGlobalCancel"}


@pytest.mark.parametrize("relative_path", ["src/services/order_stream_tws.py", "scripts/work_order_stream.py"])
def test_stream_code_never_places_or_cancels_a_broker_order(relative_path: str) -> None:
    tree = ast.parse((REPO_ROOT / relative_path).read_text())
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}

    assert names.isdisjoint(FORBIDDEN_BROKER_CALLS)
