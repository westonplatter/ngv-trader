"""Characterization of the TWS trade sync: what one ``ib.fills()`` batch turns into.

The TWS path is dormant (not registered with the jobs worker) but kept
reversible, so its behavior is pinned here with a duck-typed IB: parent
resolution by permId, the BAG combo fill plus its legs, the lookback window,
and revision supersession.

Anonymized IBKR shapes only (docs/ibkr-sample-data.md).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ib_async import IB
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Account, Trade, TradeExecution
from src.services.trade_sync_tws import sync_trades_with_ib

ACCOUNT = "U8675309"
UTC = timezone.utc
NOW = datetime.now(UTC)

STK_EXEC = "0000wxyz.00000001.01.01"
BAG_EXEC = "0000wxyz.00000007.01.01"
LEG_CALL_EXEC = "0000wxyz.00000007.02.01"
LEG_PUT_EXEC = "0000wxyz.00000007.03.01"
STALE_EXEC = "0000wxyz.00000008.01.01"
REVISED_V1 = "0000ijkl.00000009.01.01"
REVISED_V2 = "0000ijkl.00000009.01.02"


def _fill(
    exec_id: str,
    *,
    perm_id: int,
    order_id: int,
    side: str = "BOT",
    shares: float = 1.0,
    price: float = 100.0,
    sec_type: str = "STK",
    symbol: str = "BABA",
    con_id: int = 123456789,
    when: datetime | None = None,
    commission: float = -1.0,
    order_ref: str | None = None,
) -> Any:
    return SimpleNamespace(
        execution=SimpleNamespace(
            execId=exec_id,
            time=when or (NOW - timedelta(hours=2)),
            acctNumber=ACCOUNT,
            exchange="SMART",
            side=side,
            shares=shares,
            price=price,
            permId=perm_id,
            orderId=order_id,
            cumQty=shares,
            avgPrice=price,
            orderRef=order_ref,
            liquidation=0,
            openClose="O",
            positionEffect=None,
        ),
        commissionReport=SimpleNamespace(commission=commission, currency="USD", realizedPNL=0.0),
        contract=SimpleNamespace(conId=con_id, symbol=symbol, secType=sec_type, exchange="SMART", currency="USD", localSymbol=symbol),
    )


def _fills() -> list[Any]:
    return [
        # 1. A plain stock fill.
        _fill(STK_EXEC, perm_id=8888888, order_id=11, shares=10.0, price=100.0),
        # 2. A two-leg spread: IB delivers the BAG fill itself plus one fill per leg,
        #    all under one permId.
        _fill(BAG_EXEC, perm_id=9999999, order_id=12, shares=2.0, price=2.0, sec_type="BAG", symbol="ES", con_id=28812380),
        _fill(LEG_CALL_EXEC, perm_id=9999999, order_id=12, shares=2.0, price=5.0, sec_type="OPT", symbol="ES", con_id=345678901),
        _fill(LEG_PUT_EXEC, perm_id=9999999, order_id=12, side="SLD", shares=2.0, price=3.0, sec_type="OPT", symbol="ES", con_id=456789012),
        # 3. A fill older than the lookback window.
        _fill(STALE_EXEC, perm_id=6666666, order_id=13, when=NOW - timedelta(days=30)),
        # 4. A corrected fill: two revisions of one execution.
        _fill(REVISED_V1, perm_id=7777777, order_id=14, shares=5.0, price=20.0, symbol="GLD", con_id=678901234),
        _fill(REVISED_V2, perm_id=7777777, order_id=14, shares=5.0, price=21.0, symbol="GLD", con_id=678901234),
    ]


class FakeIB:
    def __init__(self, fills: list[Any]) -> None:
        self._fills = fills
        self.filters: list[Any] = []

    def reqExecutions(self, exec_filter: Any) -> None:  # noqa: N802 — ib_async name
        self.filters.append(exec_filter)

    def fills(self) -> list[Any]:
        return self._fills


@pytest.fixture(autouse=True)
def _clean(engine: Engine) -> Iterator[None]:
    def wipe() -> None:
        with engine.begin() as conn:
            for account_id in conn.execute(text("SELECT id FROM accounts WHERE account = :a"), {"a": ACCOUNT}).scalars().all():
                conn.execute(text("DELETE FROM trade_executions WHERE account_id = :id"), {"id": account_id})
                conn.execute(text("DELETE FROM trades WHERE account_id = :id"), {"id": account_id})
                conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})

    wipe()
    yield
    wipe()


def _run(engine: Engine, fills: list[Any] | None = None) -> dict[str, Any]:
    return sync_trades_with_ib(engine, ib=cast("IB", FakeIB(fills if fills is not None else _fills())), lookback_days=7)


def _executions(session: Session) -> dict[str, TradeExecution]:
    account = session.execute(select(Account).where(Account.account == ACCOUNT)).scalar_one()
    return {row.ib_exec_id: row for row in session.execute(select(TradeExecution).where(TradeExecution.account_id == account.id)).scalars().all()}


def test_metrics_and_window(engine: Engine) -> None:
    metrics = _run(engine)
    assert metrics["fetched_executions_count"] == 7
    assert metrics["inserted_executions_count"] == 6  # the stale fill is skipped
    assert metrics["updated_executions_count"] == 0
    assert metrics["canonical_changes_count"] == 1
    assert metrics["touched_trades_count"] == 3  # stock, spread, revised fill
    assert datetime.fromisoformat(metrics["window_start"]) < datetime.fromisoformat(metrics["window_end"])
    with Session(engine) as session:
        assert STALE_EXEC not in _executions(session)


def test_plain_fill_resolves_its_parent_by_perm_id(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        ex = _executions(session)[STK_EXEC]
        assert ex.exec_role == "standalone"
        assert ex.side == "BUY"  # BOT normalizes
        assert ex.ib_perm_id == 8888888
        assert ex.data_source == "tws"
        assert ex.flex_transaction_id is None
        assert ex.raw["execution"]["execId"] == STK_EXEC
        assert ex.raw["commissionReport"]["commission"] == -1.0
        assert ex.raw["contract"]["secType"] == "STK"
        trade = session.get(Trade, ex.trade_id)
        assert trade is not None
        assert (trade.ib_perm_id, trade.symbol, trade.side, trade.sec_type) == (8888888, "BABA", "BUY", "STK")
        assert trade.data_source == "tws"
        assert trade.total_quantity == 10.0
        assert trade.avg_price == 100.0


def test_bag_fill_is_the_summary_and_its_siblings_become_legs(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        execs = _executions(session)
        bag, call, put = execs[BAG_EXEC], execs[LEG_CALL_EXEC], execs[LEG_PUT_EXEC]
        assert bag.trade_id == call.trade_id == put.trade_id
        assert (bag.exec_role, call.exec_role, put.exec_role) == ("combo_summary", "leg", "leg")
        assert put.side == "SELL"
        trade = session.get(Trade, bag.trade_id)
        assert trade is not None
        assert trade.sec_type == "BAG"
        assert trade.ib_perm_id == 9999999
        # Aggregates come from the BAG fill only.
        assert trade.total_quantity == 2.0
        assert trade.avg_price == 2.0


def test_later_revision_supersedes_the_earlier_one(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        execs = _executions(session)
        v1, v2 = execs[REVISED_V1], execs[REVISED_V2]
        assert (v1.is_canonical, v2.is_canonical) == (False, True)
        assert v1.trade_id == v2.trade_id
        trade = session.get(Trade, v1.trade_id)
        assert trade is not None
        assert trade.avg_price == 21.0


def test_rerun_is_idempotent(engine: Engine) -> None:
    _run(engine)
    with Session(engine) as session:
        before = {k: (v.trade_id, v.exec_role, v.is_canonical) for k, v in _executions(session).items()}
        trade_ids = {v.trade_id for v in _executions(session).values()}
    second = _run(engine)
    with Session(engine) as session:
        assert {k: (v.trade_id, v.exec_role, v.is_canonical) for k, v in _executions(session).items()} == before
        assert {v.trade_id for v in _executions(session).values()} == trade_ids
    assert second["canonical_changes_count"] == 0
    assert second["inserted_executions_count"] == 0
    assert second["updated_executions_count"] == 6
