"""`GET /positions` overlay disposal and mark freshness (U3, U5).

The bug this guards: a position closed after the last TWS capture kept its
``live_positions`` row and rendered as still-held, because the live-only branch
could not tell "opened since the snapshot" from "closed since the capture".
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import LatestQuote
from tests.trade_group_factories import (
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_live_position,
    make_position,
)

BASE = "/api/v1/positions"
UTC = timezone.utc


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose requests run inside the test's rolled-back session."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _row(payload: list[dict], con_id: int) -> dict | None:
    return next((row for row in payload if row["con_id"] == con_id), None)


def _quote_at(session: Session, con_id: int, market_ts: datetime, mark: float = 73.0) -> None:
    session.add(LatestQuote(con_id=con_id, mark=mark, market_ts=market_ts, ingested_at=market_ts))
    session.flush()


def test_superseded_live_only_row_is_absent_while_a_current_one_is_served(client, db_session):
    account = make_account(db_session)
    # A settled row on another instrument dates the account.
    make_position(db_session, account=account, con_id=CON_NG, fetched_at=datetime.now(UTC))
    # Closed: overlay row from days ago, no settled row of its own.
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=datetime.now(UTC) - timedelta(days=4))
    # Opened since the snapshot: same shape, current capture.
    make_live_position(db_session, account=account, con_id=CON_ES, fetched_at=datetime.now(UTC))

    payload = client.get(BASE).json()

    assert _row(payload, CON_CL) is None, "a closed position must not render as held"
    assert _row(payload, CON_ES)["source"] == "live", "a position opened since the snapshot must still show"


def test_live_row_with_a_settled_counterpart_is_flagged_not_dropped(client, db_session):
    """R7: a stale overlay on a *held* position is marked, never removed."""
    account = make_account(db_session)
    make_position(db_session, account=account, con_id=CON_CL, fetched_at=datetime.now(UTC))
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=datetime.now(UTC) - timedelta(days=4))

    row = _row(client.get(BASE).json(), CON_CL)

    assert row is not None and row["live_is_stale"] is True


def test_account_with_no_settled_snapshot_keeps_its_live_only_rows(client, db_session):
    """Nothing to compare against means nothing can be superseded."""
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=datetime.now(UTC) - timedelta(days=4))

    assert _row(client.get(BASE).json(), CON_CL) is not None


def test_stale_futures_mark_is_withheld_without_borrowing_the_settled_mark(client, db_session):
    account = make_account(db_session)
    make_position(db_session, account=account, con_id=CON_CL, mark_price=99.0, fetched_at=datetime.now(UTC))
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=datetime.now(UTC))
    _quote_at(db_session, CON_CL, datetime.now(UTC) - timedelta(minutes=90))

    row = _row(client.get(BASE).json(), CON_CL)

    assert row["mark"] is None and row["live_unrealized"] is None
    assert row["mark_price"] == 99.0, "the settled mark stays in its own column"


def test_stale_equity_mark_is_still_served(client, db_session):
    """An equity's last print is its close and stays valid all evening."""
    account = make_account(db_session)
    pos = make_position(db_session, account=account, con_id=CON_ES, fetched_at=datetime.now(UTC))
    live = make_live_position(db_session, account=account, con_id=CON_ES, fetched_at=datetime.now(UTC))
    pos.sec_type = live.sec_type = "STK"
    pos.multiplier = live.multiplier = "1"
    db_session.flush()
    _quote_at(db_session, CON_ES, datetime.now(UTC) - timedelta(hours=6), mark=117.98)

    assert _row(client.get(BASE).json(), CON_ES)["mark"] is not None
