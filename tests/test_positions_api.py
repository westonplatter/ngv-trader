"""`GET /positions` overlay disposal and mark freshness (U3, U5).

The bug this guards: a position closed after the last TWS capture kept its
``live_positions`` row and rendered as still-held, because the live-only branch
could not tell "opened since the snapshot" from "closed since the capture".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from src.models import LatestQuote
from src.services.intraday_overlay import ct_date, is_overlay_superseded
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


def _row(payload: list[dict], con_id: int) -> dict | None:
    return next((row for row in payload if row["con_id"] == con_id), None)


def _quote_at(session: Session, con_id: int, market_ts: datetime, mark: float = 73.0) -> None:
    session.add(LatestQuote(con_id=con_id, mark=mark, market_ts=market_ts, ingested_at=market_ts))
    session.flush()


def test_settled_snapshot_is_dated_on_the_same_clock_the_supersede_check_uses(db_session):
    """Guards the invariant the overlay tests below rest on.

    ``date.today()`` reads the *process* timezone. On a UTC machine after 00:00
    UTC -- which is where CI runs -- that dates a snapshot a day ahead of its
    own capture, and every fresh overlay then reads as superseded by it.
    """
    captured_at = datetime.now(UTC)
    position = make_position(db_session, account=make_account(db_session), con_id=CON_NG, fetched_at=captured_at)

    assert position.as_of_date == ct_date(captured_at)
    assert not is_overlay_superseded(captured_at, position.as_of_date)


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
    assert row["live_fetched_at"] is not None, "and how old the stale capture is"


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


class TestAvgCostUnits:
    """Settled avg_cost is per-unit; every consumer expects multiplier-inclusive.

    Cost basis is computed downstream as qty x avg_cost with no multiplier, so a
    settled-backed contract row reported basis 100x/1000x too small.
    """

    def test_settled_only_row_reports_multiplier_inclusive_cost(self, client, db_session):
        account = make_account(db_session)
        # FlexQuery stores the per-unit price; multiplier 1000 (a CL-shaped future).
        make_position(
            db_session,
            account=account,
            con_id=CON_CL,
            quantity=1.0,
            avg_cost=77.26,
            multiplier="1000",
            fetched_at=datetime.now(UTC),
        )

        row = _row(client.get(BASE).json(), CON_CL)

        assert row["avg_cost"] == pytest.approx(77_260.0)
        assert row["avg_cost"] * row["position"] == pytest.approx(77_260.0), "qty x avg_cost is dollars"

    def test_stock_row_is_unchanged_by_normalization(self, client, db_session):
        """Multiplier 1 -- the case where the bug could never show."""
        account = make_account(db_session)
        pos = make_position(
            db_session,
            account=account,
            con_id=CON_ES,
            quantity=109.0,
            avg_cost=49.11,
            multiplier="1",
            fetched_at=datetime.now(UTC),
        )
        pos.sec_type = "STK"
        db_session.flush()

        row = _row(client.get(BASE).json(), CON_ES)

        assert row["avg_cost"] == pytest.approx(49.11)
