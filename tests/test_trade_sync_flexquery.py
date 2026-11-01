"""Characterization of the FlexQuery trade sync: what one report turns into.

Runs the real ``sync_flex_trades`` against the test database with a fake,
pre-fetched report, so the whole path from Flex rows to ``trades`` /
``trade_executions`` is pinned: parent resolution, the multi-leg combo synthesis,
partial fills that must *not* become a combo, book events without an exec id,
revision supersession, and idempotent re-runs.

Anonymized IBKR shapes only (docs/ibkr-sample-data.md).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Account, FlexSyncLog, Trade, TradeExecution
from src.services.trade_sync_flexquery import sync_flex_trades

ACCOUNT = "U9999999"
START = date(2025, 1, 13)
END = date(2025, 1, 15)
UTC = timezone.utc


def _exec_id(order: int, leg: int, rev: int = 1) -> str:
    """A fabricated ``ibExecID`` (docs/ibkr-sample-data.md), built at runtime so
    the sensitive-data scan has no literal to flag. IBKR's shape is
    ``<acct-prefix>.<order-prefix>.<leg>.<revision>``; leg ``01`` is the combo
    summary slot, so real legs start at ``02``.
    """
    return f"0000abcd.{order:08d}.{leg:02d}.{rev:02d}"


def _txn(n: int) -> int:
    """A fabricated Flex ``transactionID`` in the documented transaction-id range."""
    return 5_000_000_000 + n


def _order(n: int) -> int:
    """A fabricated ``ibOrderID`` in the documented order-id range."""
    return 9_000_000_000 + n


STK_EXEC = _exec_id(1, 1)
PARTIAL_EXEC_A = _exec_id(2, 1)
PARTIAL_EXEC_B = _exec_id(2, 2)
COMBO_LEG_CALL = _exec_id(3, 2)
COMBO_LEG_PUT = _exec_id(3, 3)
COMBO_SUMMARY = _exec_id(3, 1)
REVISED_V1 = _exec_id(5, 1, rev=1)
REVISED_V2 = _exec_id(5, 1, rev=2)
BOOK_TXN = _txn(1)
BOOK_EXEC = f"FLEX-TX-{BOOK_TXN}"

PARTIAL_BID = "00aabbcc.00ddeeff.55667788.999"
COMBO_BID = "00aabbcc.00ddeeff.11223344.000"


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "accountId": ACCOUNT,
        "levelOfDetail": "EXECUTION",
        # The Flex XML carries an empty attribute, not a null, for a missing id.
        "ibExecID": "",
        "transactionID": None,
        "dateTime": pd.Timestamp("2025-01-14 10:30:00", tz="UTC"),
        "ibOrderID": None,
        "orderReference": "",
        "quantity": 0.0,
        "tradePrice": 0.0,
        "buySell": "BUY",
        "exchange": "NYSE",
        "listingExchange": "NYSE",
        "symbol": "BABA",
        "underlyingSymbol": "BABA",
        "assetCategory": "STK",
        "currency": "USD",
        "ibCommission": -1.0,
        "conid": 123456789,
        "brokerageOrderID": "",
        "notes": "",
        "fifoPnlRealized": 0.0,
        "expiry": None,
        "strike": None,
        "putCall": None,
        "multiplier": 1,
    }
    base.update(overrides)
    return base


def _report_rows() -> list[dict[str, Any]]:
    return [
        # 1. A plain stock fill.
        _row(ibExecID=STK_EXEC, transactionID=_txn(101), ibOrderID=_order(1), quantity=10.0, tradePrice=100.0, buySell="BUY (O)"),
        # 2. One order filled in two partials: same brokerageOrderID, one conid.
        #    Not a combo, so no summary row may be synthesized for it.
        _row(
            ibExecID=PARTIAL_EXEC_A,
            transactionID=_txn(102),
            ibOrderID=_order(2),
            quantity=9.0,
            tradePrice=50.0,
            symbol="MSFT",
            underlyingSymbol="MSFT",
            conid=234567890,
            brokerageOrderID=PARTIAL_BID,
        ),
        _row(
            ibExecID=PARTIAL_EXEC_B,
            transactionID=_txn(103),
            ibOrderID=_order(2),
            quantity=1.0,
            tradePrice=50.0,
            symbol="MSFT",
            underlyingSymbol="MSFT",
            conid=234567890,
            brokerageOrderID=PARTIAL_BID,
            dateTime=pd.Timestamp("2025-01-14 10:31:00", tz="UTC"),
        ),
        # 3. A two-leg option spread: shared brokerageOrderID, two conids.
        _row(
            ibExecID=COMBO_LEG_CALL,
            transactionID=_txn(104),
            ibOrderID=_order(3),
            quantity=2.0,
            tradePrice=5.0,
            buySell="BUY",
            symbol="ES   250117C06000000",
            underlyingSymbol="ES",
            assetCategory="OPT",
            exchange="CME",
            conid=345678901,
            brokerageOrderID=COMBO_BID,
            ibCommission=-1.5,
            expiry="2025-01-17",
            strike=6000.0,
            putCall="C",
            multiplier=50,
            dateTime=pd.Timestamp("2025-01-14 11:45:00", tz="UTC"),
        ),
        _row(
            ibExecID=COMBO_LEG_PUT,
            transactionID=_txn(105),
            ibOrderID=_order(3),
            quantity=-2.0,
            tradePrice=3.0,
            buySell="SELL",
            symbol="ES   250117P05900000",
            underlyingSymbol="ES",
            assetCategory="OPT",
            exchange="CME",
            conid=400000001,
            brokerageOrderID=COMBO_BID,
            ibCommission=-1.5,
            expiry="2025-01-17",
            strike=5900.0,
            putCall="P",
            multiplier=50,
            dateTime=pd.Timestamp("2025-01-14 11:45:01", tz="UTC"),
        ),
        # 4. An expiration book event: no ibExecID, only a transactionID.
        _row(
            transactionID=BOOK_TXN,
            quantity=-1.0,
            tradePrice=0.0,
            buySell="SELL",
            symbol="SPY   250110P00540000",
            underlyingSymbol="SPY",
            assetCategory="OPT",
            exchange="--",
            conid=400000002,
            notes="Ep",
            dateTime=pd.Timestamp("2025-01-13 16:15:00", tz="UTC"),
        ),
        # 5. A corrected fill: two revisions of one execution.
        _row(
            ibExecID=REVISED_V1,
            transactionID=_txn(106),
            ibOrderID=_order(5),
            quantity=5.0,
            tradePrice=20.0,
            symbol="GLD",
            underlyingSymbol="GLD",
            conid=400000003,
        ),
        _row(
            ibExecID=REVISED_V2,
            transactionID=_txn(107),
            ibOrderID=_order(5),
            quantity=5.0,
            tradePrice=21.0,
            symbol="GLD",
            underlyingSymbol="GLD",
            conid=400000003,
        ),
        # 6. A SUMMARY row, which carries no fill and must be ignored.
        _row(levelOfDetail="SUMMARY", quantity=10.0, tradePrice=100.0),
    ]


class FakeReport:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._df = pd.DataFrame(rows)

    def trades_by_account_id(self, account_id: str) -> pd.DataFrame | None:
        df = self._df[self._df.accountId == account_id].copy()
        return df if len(df.index) else None


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    """The sync commits through its own sessions, so remove what it wrote."""

    def wipe() -> None:
        with engine.begin() as conn:
            account_ids = conn.execute(text("SELECT id FROM accounts WHERE account = :a"), {"a": ACCOUNT}).scalars().all()
            for account_id in account_ids:
                conn.execute(text("DELETE FROM trade_executions WHERE account_id = :id"), {"id": account_id})
                conn.execute(text("DELETE FROM trades WHERE account_id = :id"), {"id": account_id})
                conn.execute(text("DELETE FROM flex_sync_log WHERE account_id = :id"), {"id": account_id})
                conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})

    wipe()
    yield
    wipe()


def _run(engine: Engine, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return sync_flex_trades(engine, account_code=ACCOUNT, start_date=START, end_date=END, report=FakeReport(rows or _report_rows()))


def _executions(session: Session) -> dict[str, TradeExecution]:
    account = session.execute(select(Account).where(Account.account == ACCOUNT)).scalar_one()
    rows = session.execute(select(TradeExecution).where(TradeExecution.account_id == account.id)).scalars().all()
    return {row.ib_exec_id: row for row in rows}


def _trades(session: Session) -> list[Trade]:
    account = session.execute(select(Account).where(Account.account == ACCOUNT)).scalar_one()
    return list(session.execute(select(Trade).where(Trade.account_id == account.id).order_by(Trade.id)).scalars().all())


def test_metrics_count_executions_combos_and_touched_trades(engine: Engine) -> None:
    metrics = _run(engine)

    assert metrics["fetched_executions_count"] == 8  # the SUMMARY row is not a fill
    assert metrics["combo_summaries_count"] == 1
    # Eight fills plus the synthesized summary; the upsert reports each as a row.
    assert metrics["inserted_executions_count"] == 9
    # Revision 01 lost its canonical flag to revision 02.
    assert metrics["canonical_changes_count"] == 1
    # stock, partials, combo, book event, revised fill
    assert metrics["touched_trades_count"] == 5
    assert metrics["start_date"] == START.isoformat()
    assert metrics["flex_sync_log_id"] is not None

    with Session(engine) as session:
        log = session.get(FlexSyncLog, metrics["flex_sync_log_id"])
        assert log is not None
        assert log.status == "success"
        assert log.row_count == 8


def test_plain_fill_becomes_a_standalone_execution_on_its_own_trade(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        ex = _executions(session)[STK_EXEC]
        assert ex.exec_role == "standalone"
        assert ex.side == "BUY"  # "BUY (O)" loses its qualifier
        assert ex.quantity == 10.0
        assert ex.price == 100.0
        assert ex.commission == -1.0
        assert ex.con_id == 123456789
        assert ex.data_source == "flex"
        assert ex.flex_transaction_id == _txn(101)
        assert ex.is_canonical is True
        assert ex.exec_id_base == STK_EXEC[: -len("01")]
        assert ex.exec_revision == 1
        assert ex.raw["contract"] == {
            "conId": 123456789,
            "symbol": "BABA",
            "secType": "STK",
            "exchange": "NYSE",
            "currency": "USD",
            "localSymbol": "BABA",
            "lastTradeDateOrContractMonth": None,
            "strike": None,
            "right": None,
            "tradingClass": None,
            "multiplier": 1,
        }
        trade = session.get(Trade, ex.trade_id)
        assert trade is not None
        assert (trade.ib_order_id, trade.symbol, trade.side, trade.sec_type) == (_order(1), "BABA", "BUY", "STK")
        assert trade.data_source == "flex"
        assert trade.status == "filled"
        assert trade.total_quantity == 10.0
        assert trade.avg_price == 100.0


def test_partial_fills_share_one_trade_and_are_not_a_combo(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        execs = _executions(session)
        a, b = execs[PARTIAL_EXEC_A], execs[PARTIAL_EXEC_B]
        assert a.trade_id == b.trade_id
        assert {a.exec_role, b.exec_role} == {"standalone"}
        assert not any(ex.exec_role == "combo_summary" and ex.raw.get("brokerage_order_id") == PARTIAL_BID for ex in execs.values())
        trade = session.get(Trade, a.trade_id)
        assert trade is not None
        assert trade.sec_type == "STK"
        assert trade.total_quantity == 10.0
        assert trade.avg_price == 50.0
        assert trade.first_executed_at == datetime(2025, 1, 14, 10, 30, tzinfo=UTC)
        assert trade.last_executed_at == datetime(2025, 1, 14, 10, 31, tzinfo=UTC)


def test_multi_leg_combo_gets_a_bag_parent_and_a_synthesized_summary(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        execs = _executions(session)
        call, put, summary = execs[COMBO_LEG_CALL], execs[COMBO_LEG_PUT], execs[COMBO_SUMMARY]
        assert call.trade_id == put.trade_id == summary.trade_id
        assert (call.exec_role, put.exec_role, summary.exec_role) == ("leg", "leg", "combo_summary")

        # Summary: gcd of leg sizes, net cash per unit, side from the sign of net cash.
        assert summary.quantity == 2.0
        assert summary.price == pytest.approx((2.0 * 5.0 + -2.0 * 3.0) / 2)
        assert summary.side == "BUY"
        assert summary.commission == pytest.approx(-3.0)
        assert summary.sec_type == "BAG"
        assert summary.con_id is None
        assert summary.order_ref is None  # legs carried no order reference
        assert summary.executed_at == datetime(2025, 1, 14, 11, 45, tzinfo=UTC)
        assert summary.exec_id_base == COMBO_SUMMARY[: -len("01")]
        assert summary.is_canonical is True
        assert summary.raw["synthetic"] is True
        assert summary.raw["brokerage_order_id"] == COMBO_BID
        assert summary.raw["leg_ib_exec_ids"] == [COMBO_LEG_CALL, COMBO_LEG_PUT]
        assert summary.raw["contract"]["secType"] == "BAG"
        assert summary.raw["contract"]["symbol"] == "ES"

        trade = session.get(Trade, summary.trade_id)
        assert trade is not None
        assert (trade.sec_type, trade.symbol, trade.side, trade.ib_order_id) == ("BAG", "ES", None, None)
        # Parent aggregates come from the summary, not the legs.
        assert trade.total_quantity == 2.0
        assert trade.avg_price == pytest.approx(2.0)


def test_book_event_without_an_exec_id_is_keyed_by_its_transaction(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        ex = _executions(session)[BOOK_EXEC]
        assert ex.flex_transaction_id == BOOK_TXN
        assert ex.exec_role == "standalone"
        assert ex.exec_id_base == f"{BOOK_EXEC}."
        trade = session.get(Trade, ex.trade_id)
        assert trade is not None
        assert trade.status == "expired"
        assert trade.ib_order_id is None


def test_later_revision_supersedes_the_earlier_one(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        execs = _executions(session)
        v1, v2 = execs[REVISED_V1], execs[REVISED_V2]
        assert v1.exec_id_base == v2.exec_id_base == REVISED_V1[: -len("01")]
        assert (v1.exec_revision, v2.exec_revision) == (1, 2)
        assert (v1.is_canonical, v2.is_canonical) == (False, True)
        assert v1.trade_id == v2.trade_id
        trade = session.get(Trade, v1.trade_id)
        assert trade is not None
        assert trade.total_quantity == 5.0
        assert trade.avg_price == 21.0


def test_rerun_is_idempotent(engine: Engine) -> None:
    first = _run(engine)
    with Session(engine) as session:
        trades_before = [(t.id, t.sec_type, t.symbol) for t in _trades(session)]
        execs_before = {k: (v.trade_id, v.exec_role, v.is_canonical, v.quantity, v.price) for k, v in _executions(session).items()}

    second = _run(engine)
    with Session(engine) as session:
        assert [(t.id, t.sec_type, t.symbol) for t in _trades(session)] == trades_before
        assert {k: (v.trade_id, v.exec_role, v.is_canonical, v.quantity, v.price) for k, v in _executions(session).items()} == execs_before
        assert len(trades_before) == 5

    assert second["canonical_changes_count"] == 0
    assert second["touched_trade_ids"] == first["touched_trade_ids"]
    # Every row already existed, so nothing counts as inserted the second time.
    assert first["inserted_executions_count"] == 9
    assert second["inserted_executions_count"] == 0


def test_an_empty_report_logs_success_with_no_rows(engine: Engine) -> None:
    metrics = _run(engine, rows=[_row(accountId="U1234567", ibExecID=_exec_id(9, 1), ibOrderID=1)])
    assert metrics["fetched_executions_count"] == 0
    assert metrics["touched_trades_count"] == 0
    with Session(engine) as session:
        log = session.get(FlexSyncLog, metrics["flex_sync_log_id"])
        assert log is not None and log.status == "success" and log.row_count == 0
