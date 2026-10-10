"""A contract split across trade groups is counted once, not in full in each.

Two groups that each opened one lot of the same contract used to both show the
whole account position (and its unrealized P&L) in Open Positions. Each group
now holds only what its own tagged fills opened.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import Account, TradeExecution, TradeGroup
from src.services.execution_pnl import execution_lifecycle
from src.services.trade_group_pnl import compute_trade_group_pnl, trade_group_batch_pnls
from tests.trade_group_factories import (
    CON_CL,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
    make_live_position,
    make_position,
    make_quote,
)

BASE = "/api/v1/trade-groups"
ACCOUNT_UNREALIZED = 4_000.0


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose requests run inside the test's rolled-back session."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _fill(session: Session, group: TradeGroup | None, account: Account, seq: int, *, side: str, quantity: float, lifecycle: str) -> TradeExecution:
    execution = make_execution(session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(seq), side=side, quantity=quantity)
    execution.raw = {**execution.raw, "openCloseIndicator": lifecycle}
    session.flush()
    return execution


def _split_short(session: Session) -> tuple[Account, TradeGroup, TradeGroup]:
    """Account short 2 lots: one opened under each group.

    Group B also carries the sell that closed an earlier untagged long before
    its own open — a same-direction close that is not B's exposure.
    """
    account = make_account(session)
    group_a = make_group(session, "CL calendar A", account.id)
    group_b = make_group(session, "CL calendar B", account.id)
    _fill(session, None, account, 91000001, side="BUY", quantity=1.0, lifecycle="O")
    _fill(session, group_b, account, 91000002, side="SELL", quantity=-1.0, lifecycle="C")
    _fill(session, group_b, account, 91000003, side="SELL", quantity=-1.0, lifecycle="O")
    _fill(session, group_a, account, 91000004, side="SELL", quantity=-1.0, lifecycle="O")
    make_position(session, account=account, con_id=CON_CL, quantity=-2.0, unrealized=ACCOUNT_UNREALIZED)
    return account, group_a, group_b


def test_each_group_shows_only_its_own_lot(client: TestClient, db_session: Session) -> None:
    _, group_a, group_b = _split_short(db_session)

    bodies = [client.get(f"{BASE}/{group.id}/executions").json() for group in (group_a, group_b)]

    for body in bodies:
        [position] = body["open_positions"]
        assert position["position"] == pytest.approx(-1.0)
        assert position["fifo_pnl_unrealized"] == pytest.approx(ACCOUNT_UNREALIZED / 2)
        assert body["total_unrealized_pnl"] == pytest.approx(ACCOUNT_UNREALIZED / 2)
    assert sum(body["total_unrealized_pnl"] for body in bodies) == pytest.approx(ACCOUNT_UNREALIZED)


@pytest.mark.parametrize("include_intraday", [True, False])
def test_batch_and_single_group_paths_apportion_the_same_way(db_session: Session, include_intraday: bool) -> None:
    _, group_a, group_b = _split_short(db_session)

    batch = trade_group_batch_pnls(db_session, [group_a.id, group_b.id], include_intraday=include_intraday)

    for group in (group_a, group_b):
        assert batch[group.id].settled_unrealized_pnl == pytest.approx(ACCOUNT_UNREALIZED / 2)
        assert compute_trade_group_pnl(db_session, group.id).settled_unrealized_pnl == pytest.approx(ACCOUNT_UNREALIZED / 2)


def test_group_that_closed_its_own_lot_holds_nothing(client: TestClient, db_session: Session) -> None:
    """The account still holds the contract, but not through this group."""
    account = make_account(db_session)
    closed = make_group(db_session, "CL round trip", account.id)
    _fill(db_session, closed, account, 92000001, side="BUY", quantity=1.0, lifecycle="O")
    _fill(db_session, closed, account, 92000002, side="SELL", quantity=-1.0, lifecycle="C")
    _fill(db_session, None, account, 92000003, side="BUY", quantity=1.0, lifecycle="O")
    make_position(db_session, account=account, con_id=CON_CL, quantity=1.0)

    body = client.get(f"{BASE}/{closed.id}/executions").json()

    assert body["open_positions"] == []
    assert not body["total_unrealized_pnl"]


def test_unsettled_lot_takes_its_share_of_the_live_position_only(client: TestClient, db_session: Session) -> None:
    """A lot opened today has no part of the settled snapshot, which predates it."""
    account = make_account(db_session)
    settled_group = make_group(db_session, "CL settled lot", account.id)
    today_group = make_group(db_session, "CL today lot", account.id)
    _fill(db_session, settled_group, account, 93000001, side="SELL", quantity=-1.0, lifecycle="O")
    make_position(db_session, account=account, con_id=CON_CL, quantity=-1.0, unrealized=ACCOUNT_UNREALIZED)
    make_live_position(db_session, account=account, con_id=CON_CL, quantity=-2.0)
    make_quote(db_session, CON_CL, mark=73.0)
    make_live_execution(db_session, account=account, con_id=CON_CL, exec_id=make_exec_id(93000002), group=today_group)

    settled_body = client.get(f"{BASE}/{settled_group.id}/executions").json()
    today_body = client.get(f"{BASE}/{today_group.id}/executions").json()

    [settled_lot] = settled_body["open_positions"]
    [today_lot] = today_body["open_positions"]
    assert settled_lot["position"] == pytest.approx(-1.0)
    assert today_lot["position"] == pytest.approx(-1.0)
    assert settled_lot["live_unrealized"] + today_lot["live_unrealized"] == pytest.approx(2 * settled_lot["live_unrealized"])
    assert settled_body["total_unrealized_pnl"] == pytest.approx(ACCOUNT_UNREALIZED)
    assert today_body["total_unrealized_pnl"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"openCloseIndicator": "O"}, "Open"),
        ({"openCloseIndicator": "C;O"}, None),
        ({"execution": {"openClose": "C"}}, "Close"),
        ({}, None),
        (None, None),
    ],
)
def test_execution_lifecycle_reads_both_raw_shapes(raw: dict | None, expected: str | None) -> None:
    assert execution_lifecycle(raw) == expected
