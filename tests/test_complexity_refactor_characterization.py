"""Characterization tests for functions split to satisfy the Ruff complexity limits.

These pin the behavior of code that had no direct tests when it was restructured
(contract-month parsing, order input validation, option-field parsing, strike
filtering, broker order sync, the job payload parsers). They were written against
the pre-split code and must keep passing unchanged.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.schemas import _derive_option_fields
from src.models import Order, OrderEvent
from src.services import contract_sync, order_sync_tws
from src.services.cl_contracts import normalize_contract_month_input, select_front_month_future_contract
from src.services.order_mutations import OrderCreateInput, normalize_order_create_input
from src.services.position_sync_flexquery import _resolve_as_of_date
from src.workers import jobs

# ---------------------------------------------------------------------------
# cl_contracts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("   ", None),
        ("2026-03", "2026-03"),
        ("2026/03", "2026-03"),
        ("202603", "2026-03"),
        ("20260315", "2026-03"),
        ("2026-03-15", "2026-03"),
        ("March 2026", "2026-03"),
        ("mar 2026", "2026-03"),
        ("Sep, 2026", "2026-09"),
    ],
)
def test_normalize_contract_month_input_accepts(raw: str | None, expected: str | None) -> None:
    assert normalize_contract_month_input(raw) == expected


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("2026-13", "valid month"),
        ("2026-00", "valid month"),
        ("202613", "valid month"),
        ("20261315", "valid month"),
        ("2026-13-15", "YYYY-MM, YYYYMM"),
        ("junk", "YYYY-MM, YYYYMM"),
        ("2026", "YYYY-MM, YYYYMM"),
    ],
)
def test_normalize_contract_month_input_rejects(raw: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_contract_month_input(raw)


def _fut_detail(local_symbol: str, days_out: int, sec_type: str = "FUT") -> Any:
    expiry = (dt.date.today() + dt.timedelta(days=days_out)).strftime("%Y%m%d")
    contract = SimpleNamespace(
        secType=sec_type,
        lastTradeDateOrContractMonth=expiry,
        localSymbol=local_symbol,
        symbol="CL",
    )
    return SimpleNamespace(contract=contract)


class _FakeIB:
    def __init__(self, details: list[Any]) -> None:
        self._details = details
        self.qualified: list[Any] = []

    def reqContractDetails(self, _contract: Any) -> list[Any]:
        return self._details

    def qualifyContracts(self, contract: Any) -> list[Any]:
        self.qualified.append(contract)
        return [contract]


def test_select_front_month_picks_earliest_outside_the_safety_window() -> None:
    details = [
        _fut_detail("CLZ", 90),
        _fut_detail("CLF", 40),
        _fut_detail("CLX", 3),  # inside the window
        _fut_detail("CLG", -5),  # already expired
        _fut_detail("CLOPT", 20, sec_type="FOP"),  # not a future
        SimpleNamespace(contract=None),
    ]
    ib = _FakeIB(details)
    chosen = select_front_month_future_contract(ib, symbol=" cl ", exchange="NYMEX", min_days_to_expiry=7)  # type: ignore[arg-type]
    assert chosen.localSymbol == "CLF"
    assert [c.localSymbol for c in ib.qualified] == ["CLF"]


def test_select_front_month_validates_inputs() -> None:
    ib = _FakeIB([])
    with pytest.raises(ValueError, match="min_days_to_expiry"):
        select_front_month_future_contract(ib, symbol="CL", exchange="NYMEX", min_days_to_expiry=-1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="symbol must be"):
        select_front_month_future_contract(ib, symbol="  ", exchange="NYMEX")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="No CL futures contract details returned"):
        select_front_month_future_contract(ib, symbol="cl", exchange="NYMEX")  # type: ignore[arg-type]


def test_select_front_month_reports_the_nearest_contract_when_all_are_inside_the_window() -> None:
    ib = _FakeIB([_fut_detail("CLK", 5), _fut_detail("CLM", 2)])
    with pytest.raises(RuntimeError, match=r"outside the near-expiry safety window.*Nearest non-expired contract: CLM"):
        select_front_month_future_contract(ib, symbol="CL", exchange="NYMEX", min_days_to_expiry=30)  # type: ignore[arg-type]


def test_select_front_month_reports_when_nothing_is_unexpired() -> None:
    ib = _FakeIB([_fut_detail("CLK", -5)])
    with pytest.raises(RuntimeError, match="No non-expired CL futures contracts found"):
        select_front_month_future_contract(ib, symbol="CL", exchange="NYMEX")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# order_mutations.normalize_order_create_input
# ---------------------------------------------------------------------------


def _create_input(**overrides: Any) -> OrderCreateInput:
    fields: dict[str, Any] = {"account_id": 1, "symbol": "cl", "side": "buy", "quantity": 2}
    fields.update(overrides)
    return OrderCreateInput(**fields)


def test_normalize_order_create_input_uppercases_and_clears_a_market_limit_price() -> None:
    normalized = normalize_order_create_input(_create_input(limit_price=70, source=" tradebot ", request_text=" hi "))
    assert (normalized.symbol, normalized.side, normalized.order_type) == ("CL", "BUY", "MKT")
    assert normalized.limit_price is None
    assert normalized.source == "tradebot"
    assert normalized.request_text == "hi"


def test_normalize_order_create_input_keeps_a_limit_price_for_lmt() -> None:
    normalized = normalize_order_create_input(_create_input(order_type="lmt", limit_price=70))
    assert normalized.order_type == "LMT"
    assert normalized.limit_price == 70.0


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"symbol": " "}, "'symbol' must be a non-empty string"),
        ({"symbol": "/mcl", "sec_type": "STK"}, "only supported for FUT"),
        ({"symbol": "/ "}, "must include a root symbol"),
        ({"symbol": "/"}, "must include a root symbol"),
        ({"side": "hold"}, "'side' must be BUY or SELL"),
        ({"quantity": 0}, "'quantity' must be >= 1"),
        ({"sec_type": " "}, "'sec_type' must be a non-empty string"),
        ({"exchange": ""}, "'exchange' must be a non-empty string"),
        ({"currency": ""}, "'currency' must be a non-empty string"),
        ({"order_type": "stop"}, "'order_type' must be MKT or LMT"),
        ({"order_type": "LMT"}, "'limit_price' must be > 0 for LMT orders"),
        ({"order_type": "LMT", "limit_price": 0}, "'limit_price' must be > 0 for LMT orders"),
        ({"tif": ""}, "'tif' must be a non-empty string"),
        ({"source": " "}, "'source' must be a non-empty string"),
        # The first failing check wins, in the order symbol, side, quantity, sec_type, ...
        ({"symbol": "", "side": "hold"}, "'symbol' must be a non-empty string"),
        ({"side": "hold", "quantity": 0}, "'side' must be BUY or SELL"),
        ({"quantity": 0, "sec_type": ""}, "'quantity' must be >= 1"),
        ({"sec_type": "", "exchange": ""}, "'sec_type' must be a non-empty string"),
        ({"tif": "", "source": ""}, "'tif' must be a non-empty string"),
        ({"symbol": "/x", "sec_type": ""}, "only supported for FUT"),
    ],
)
def test_normalize_order_create_input_rejects(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_order_create_input(_create_input(**overrides))


# ---------------------------------------------------------------------------
# api.schemas._derive_option_fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sec_type", "local_symbol", "expected"),
    [
        ("STK", "WA4G6 C0707", (None, None)),
        ("FOP", None, (None, None)),
        ("FOP", "   ", (None, None)),
        ("FOP", "WA4G6 C0707", ("C", "0707")),
        ("FOP", "wa4g6 p0707", ("P", "0707")),
        ("OPT", "CL   MAY 26 70.5 C", ("C", "70.5")),
        ("BAG", "CL 70.5 P", ("P", "70.5")),
        ("FOP", "CL FUT", (None, None)),
    ],
)
def test_derive_option_fields(sec_type: str, local_symbol: str | None, expected: tuple[str | None, str | None]) -> None:
    order = Order(account_id=1, symbol="CL", side="BUY", quantity=1, sec_type=sec_type, local_symbol=local_symbol)
    assert _derive_option_fields(order) == expected


# ---------------------------------------------------------------------------
# contract_sync._passes_strike_filter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("strike", "fut_price", "filt", "expected"),
    [
        (70.0, 70.0, {}, True),
        (70.0, None, {"strike_gte": 70.0, "strike_lte": 70.0}, True),
        (69.0, None, {"strike_gte": 70.0}, False),
        (71.0, None, {"strike_lte": 70.0}, False),
        (63.0, 70.0, {"moneyness_gte": 90.0}, True),
        (62.0, 70.0, {"moneyness_gte": 90.0}, False),
        (76.0, 70.0, {"moneyness_lte": 110.0}, True),
        (78.0, 70.0, {"moneyness_lte": 110.0}, False),
        (10.0, None, {"moneyness_gte": 90.0}, True),  # no underlying price: moneyness is skipped
        (10.0, 0.0, {"moneyness_gte": 90.0}, True),
        (70.5, 70.0, {"modulus_eq": 0.5}, True),
        (70.25, 70.0, {"modulus_eq": 0.5}, False),
        (70.25, 70.0, {"modulus_eq": 0}, True),
        (70.25, 70.0, {"modulus_eq": None}, True),
    ],
)
def test_passes_strike_filter(strike: float, fut_price: float | None, filt: dict, expected: bool) -> None:
    assert contract_sync._passes_strike_filter(strike, fut_price, filt) is expected


# ---------------------------------------------------------------------------
# position_sync_flexquery._resolve_as_of_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (pd.Timestamp("2026-03-15 10:00"), dt.date(2026, 3, 15)),
        (dt.datetime(2026, 3, 16, 9, 30), dt.date(2026, 3, 16)),
        (dt.date(2026, 3, 17), dt.date(2026, 3, 17)),
        ("2026-03-18", None),
    ],
)
def test_resolve_as_of_date_by_value_type(value: Any, expected: dt.date | None) -> None:
    frame = pd.DataFrame({"reportDate": pd.Series([value], dtype=object)})
    assert _resolve_as_of_date(frame) == expected


def test_resolve_as_of_date_without_a_usable_column() -> None:
    assert _resolve_as_of_date(pd.DataFrame({"other": [1]})) is None
    assert _resolve_as_of_date(pd.DataFrame({"reportDate": pd.Series([None], dtype=object)})) is None


# ---------------------------------------------------------------------------
# order_sync_tws
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ib_status", "filled", "expected"),
    [
        ("Filled", 1.0, "filled"),
        (" REJECTED ", 0.0, "rejected"),
        ("Cancelled", 0.0, "cancelled"),
        ("ApiCancelled", 0.0, "cancelled"),
        ("Inactive", 0.0, "cancelled"),
        ("Submitted", 0.0, "submitted"),
        ("PendingSubmit", 0.0, "submitted"),
        ("PreSubmitted", 2.0, "partially_filled"),
        ("Submitted", 0.5, "partially_filled"),
        ("SomethingNew", 5.0, "submitted"),
        ("", 0.0, "queued"),
        (None, 3.0, "queued"),
    ],
)
def test_sync_normalize_ib_status(ib_status: str | None, filled: float, expected: str) -> None:
    assert order_sync_tws.normalize_ib_status(ib_status, filled) == expected


SAMPLE_PERM_ID = 8888888


def _sync_trade(status: str, *, filled: float = 0.0, quantity: float = 1.0, avg_price: float = 0.0) -> Any:
    return SimpleNamespace(
        order=SimpleNamespace(
            action="BUY",
            totalQuantity=quantity,
            orderType="MKT",
            lmtPrice=0.0,
            tif="DAY",
            orderId=7,
            permId=SAMPLE_PERM_ID,
            orderRef="",
            account="U1234567",
        ),
        orderStatus=SimpleNamespace(status=status, avgFillPrice=avg_price),
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
        filled=lambda: filled,
    )


def _sync_order(session: Session, status: str) -> Order:
    order = Order(account_id=1, symbol="CL", side="BUY", quantity=1, status=status)
    session.add(order)
    session.flush()
    return order


def _event_rows(session: Session, order: Order) -> list[tuple[str, str]]:
    stmt = select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.id)
    return [(e.event_type, e.message or "") for e in session.execute(stmt).scalars().all()]


def test_sync_trade_onto_order_applies_an_allowed_status_move(db_session: Session) -> None:
    order = _sync_order(db_session, "submitting")
    assert order_sync_tws._sync_trade_onto_order(db_session, order, _sync_trade("Submitted")) is True

    assert order.status == "submitted"
    assert (order.symbol, order.sec_type, order.exchange, order.con_id, order.local_symbol) == ("CL", "FUT", "NYMEX", 400000001, "CLZ6")
    assert (order.ib_order_id, order.ib_perm_id, order.contract_expiry) == (7, SAMPLE_PERM_ID, "20261120")
    assert order.submitted_at is not None
    events = _event_rows(db_session, order)
    assert [t for t, _ in events if t == "broker_order_synced_status"] == ["broker_order_synced_status"]
    assert "Broker order sync status update: ib_status=Submitted, filled=0.0, avg_fill=0.0" in events[-1][1]
    assert not [t for t, _ in events if t == "broker_order_synced_update"]


def test_sync_trade_onto_order_is_a_noop_when_nothing_changed(db_session: Session) -> None:
    order = _sync_order(db_session, "submitting")
    trade = _sync_trade("Submitted")
    order_sync_tws._sync_trade_onto_order(db_session, order, trade)
    before = _event_rows(db_session, order)

    assert order_sync_tws._sync_trade_onto_order(db_session, order, trade) is False
    assert _event_rows(db_session, order) == before


def test_sync_trade_onto_order_records_a_field_refresh_without_a_status_change(db_session: Session) -> None:
    order = _sync_order(db_session, "submitting")
    order_sync_tws._sync_trade_onto_order(db_session, order, _sync_trade("Submitted"))

    assert order_sync_tws._sync_trade_onto_order(db_session, order, _sync_trade("Submitted", quantity=3.0)) is True
    assert order.quantity == 3
    event_type, message = _event_rows(db_session, order)[-1]
    assert event_type == "broker_order_synced_update"
    assert "Broker order sync refreshed order fields: ib_status=Submitted" in message


def test_sync_trade_onto_order_forces_a_disallowed_status_move(db_session: Session) -> None:
    order = _sync_order(db_session, "filled")
    assert order_sync_tws._sync_trade_onto_order(db_session, order, _sync_trade("Submitted")) is True

    assert order.status == "submitted"
    event_type, message = _event_rows(db_session, order)[-1]
    assert event_type == "broker_order_synced_status"
    assert message == "Forced status update to submitted from broker sync."


def test_sync_trade_onto_order_stamps_completion_on_a_terminal_status(db_session: Session) -> None:
    order = _sync_order(db_session, "submitted")
    assert order_sync_tws._sync_trade_onto_order(db_session, order, _sync_trade("Filled", filled=1.0, avg_price=70.5)) is True

    assert order.status == "filled"
    assert order.completed_at is not None
    assert (order.filled_quantity, order.avg_fill_price) == (1.0, 70.5)


# ---------------------------------------------------------------------------
# workers.jobs payload parsers
# ---------------------------------------------------------------------------


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "fake-ib"


def _specs_for(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> list[Any]:
    captured: dict[str, Any] = {}

    def fake_sync(*, engine: Any, ib: Any, specs: list[Any]) -> dict:
        captured["specs"] = specs
        return {"ok": True}

    monkeypatch.setattr(contract_sync, "sync_contracts_with_ib", fake_sync)
    monkeypatch.setenv("BROKER_TWS_PORT", "4002")
    job = SimpleNamespace(payload=payload)
    assert jobs.handle_contracts_sync(job, object(), _FakePool()) == {"ok": True}  # type: ignore[arg-type]
    return captured["specs"]


def test_contracts_sync_defaults_to_the_cl_future(monkeypatch: pytest.MonkeyPatch) -> None:
    for payload in ({}, {"specs": []}, {"specs": ["not-a-dict", 3]}):
        (spec,) = _specs_for(monkeypatch, payload)
        assert (spec.symbol, spec.secType, spec.exchange, spec.currency) == ("CL", "FUT", "NYMEX", "USD")


def test_contracts_sync_builds_one_spec_per_payload_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "specs": [
            {"symbol": "ES", "sec_type": "fut", "exchange": "CME", "currency": "USD"},
            {"symbol": "AAPL", "sec_type": "STK", "exchange": "NASDAQ"},
            {"symbol": "SPY", "sec_type": "OPT", "exchange": "CBOE"},
            {"symbol": "VIX", "sec_type": "IND", "exchange": "CBOE"},
            "skipped",
        ]
    }
    specs = _specs_for(monkeypatch, payload)
    assert [(s.symbol, s.secType, s.exchange, s.currency) for s in specs] == [
        ("ES", "FUT", "CME", "USD"),
        ("AAPL", "STK", "SMART", "USD"),
        ("SPY", "OPT", "SMART", "USD"),
        ("VIX", "IND", "CBOE", "USD"),
    ]


def test_contracts_sync_requires_an_exchange(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RuntimeError, match="No exchange specified for ES FUT"):
        _specs_for(monkeypatch, {"specs": [{"symbol": "ES", "sec_type": "FUT"}]})


def _quotes_connection(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> dict[str, Any]:
    from src.services import watchlist_quotes

    def fake_refresh(*, engine: Any, watch_list_id: int, ib: Any) -> dict:
        return {"watch_list_id": watch_list_id, "ib": ib}

    monkeypatch.setattr(watchlist_quotes, "refresh_watch_list_quotes_with_ib", fake_refresh)
    pool = _FakePool()
    result = jobs.handle_watchlist_quotes_refresh(SimpleNamespace(payload=payload), object(), pool)  # type: ignore[arg-type]
    assert result == {"watch_list_id": 5, "ib": "fake-ib"}
    (call,) = pool.calls
    return call


def test_quotes_refresh_uses_payload_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROKER_TWS_PORT", raising=False)
    call = _quotes_connection(
        monkeypatch,
        {"watch_list_id": 5, "host": "10.0.0.5", "port": 4001, "client_id": 9, "connect_timeout_seconds": 3},
    )
    assert call == {"host": "10.0.0.5", "port": 4001, "client_id": 9, "connect_timeout_seconds": 3.0}


def test_quotes_refresh_falls_back_to_env_and_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BROKER_TWS_PORT", "4002")
    monkeypatch.delenv("BROKER_TWS_QUOTES_CLIENT_ID", raising=False)
    call = _quotes_connection(monkeypatch, {"watch_list_id": 5})
    assert call == {"host": "127.0.0.1", "port": 4002, "client_id": 141, "connect_timeout_seconds": 10.0}

    monkeypatch.setenv("BROKER_TWS_QUOTES_CLIENT_ID", "77")
    assert _quotes_connection(monkeypatch, {"watch_list_id": 5})["client_id"] == 77


def test_quotes_refresh_requires_a_port_and_a_watch_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BROKER_TWS_PORT", raising=False)
    with pytest.raises(RuntimeError, match="BROKER_TWS_PORT is not set"):
        _quotes_connection(monkeypatch, {"watch_list_id": 5})
    with pytest.raises(ValueError, match="requires integer 'watch_list_id'"):
        jobs.handle_watchlist_quotes_refresh(SimpleNamespace(payload={}), object(), _FakePool())  # type: ignore[arg-type]
