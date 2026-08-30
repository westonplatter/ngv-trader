"""Unit tests for the live-overlay supersede predicate and mark-freshness cap.

Pure functions over timestamps -- no DB. The boundary cases are the point: a
strict ">" on the watermark is what keeps an overnight futures capture (which
belongs to the *next* trade date) from being deleted by a same-dated snapshot.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from src.services.intraday_overlay import (
    ct_date,
    is_overlay_superseded,
    mark_if_fresh,
    superseded_cutoff,
)

MT = ZoneInfo("America/Denver")
ET = ZoneInfo("America/New_York")
UTC = timezone.utc

# 23:09 MT is 00:09 CT -- already the next day in Chicago. The shape of the
# capture behind the stale-overlay bug.
CAPTURE_LATE_MT = datetime(2025, 1, 6, 23, 9, tzinfo=MT)


def test_ct_date_rolls_a_late_mountain_evening_into_the_next_chicago_day():
    assert ct_date(CAPTURE_LATE_MT) == date(2025, 1, 7)


@pytest.mark.parametrize(
    ("capture", "as_of", "expected", "why"),
    [
        (CAPTURE_LATE_MT, date(2025, 1, 9), True, "snapshot clearly postdates the capture"),
        (CAPTURE_LATE_MT, date(2025, 1, 7), False, "strict '>': an overnight capture owns the next trade date"),
        # ~21:00 ET is inside the US overnight equity session, which IBKR stamps
        # with the next trade date. This is what a sec_type split would misfile.
        (datetime(2025, 1, 6, 21, 0, tzinfo=ET), date(2025, 1, 6), False, "overnight equity capture survives"),
        (None, date(2025, 1, 9), False, "no capture"),
        (CAPTURE_LATE_MT, None, False, "account has no settled snapshot at all"),
    ],
)
def test_is_overlay_superseded(capture, as_of, expected, why):
    assert is_overlay_superseded(capture, as_of) is expected, why


def test_cutoff_and_predicate_agree_across_a_day_boundary_sweep():
    """The SQL-shaped cutoff and the row-shaped predicate must never disagree.

    The write path filters with the cutoff and the read paths with the
    predicate; drift between them means the two disagree about what is stale.
    """
    as_of = date(2025, 1, 7)
    cutoff = superseded_cutoff(as_of)
    base = datetime(2025, 1, 5, tzinfo=UTC)
    for hours in range(96):
        capture = base + timedelta(hours=hours)
        assert is_overlay_superseded(capture, as_of) == (capture < cutoff), capture.isoformat()


@pytest.mark.parametrize(
    ("sec_type", "age", "kept", "why"),
    [
        ("FUT", timedelta(minutes=90), False, "futures trade ~23h; an hours-old mark is stale mid-session"),
        ("FUT", timedelta(minutes=10), True, "recent futures mark is live"),
        ("STK", timedelta(hours=6), True, "an equity's last print is its close and stays valid"),
        ("OPT", timedelta(hours=6), True, "equity options are not age-capped either"),
    ],
)
def test_mark_if_fresh_caps_only_continuously_traded_instruments(sec_type, age, kept, why):
    now = datetime(2025, 1, 6, 12, 0, tzinfo=UTC)
    result = mark_if_fresh(73.5, now - age, sec_type, now=now)
    assert (result is not None) is kept, why


def test_mark_if_fresh_leaves_a_mark_alone_when_its_timestamp_is_unknown():
    assert mark_if_fresh(73.5, None, "FUT") == 73.5


# ---------------------------------------------------------------------------
# Regression guard: a stale overlay must never win over a newer snapshot.
#
# This defect shipped three times in the same session -- once in the positions
# router, once in the trade-group merge, and it was briefly "fixed" by reverting
# to it. The rule is one line: is_live_stale gates the DATA, not just the label.
# ---------------------------------------------------------------------------


class _Row:
    """Minimal stand-in for a Position / LivePosition row."""

    def __init__(self, **kw):
        self.account_id = kw.get("account_id", 1)
        self.con_id = kw.get("con_id", 1000000001)
        self.symbol = kw.get("symbol", "CL")
        self.local_symbol = kw.get("local_symbol", "CLZ6")
        self.sec_type = kw.get("sec_type", "FUT")
        self.multiplier = kw.get("multiplier", "1000")
        self.right = None
        self.strike = None
        self.position = kw["position"]
        self.avg_cost = kw["avg_cost"]
        self.fetched_at = kw["fetched_at"]
        self.mark_price = kw.get("mark_price")
        self.fifo_pnl_unrealized = kw.get("fifo_pnl_unrealized")
        self.position_value = kw.get("position_value")
        self.as_of_date = kw.get("as_of_date")


def _merged(*, live_age_days: int):
    """One instrument held in both sources, with the overlay `n` days old."""
    from src.services.intraday_overlay import merge_positions

    now = datetime.now(timezone.utc)
    # Settled stores avg_cost per-unit; live stores it multiplier-inclusive.
    flex = _Row(position=2.0, avg_cost=77.26, fetched_at=now, mark_price=80.0)
    live = _Row(position=1.0, avg_cost=99_000.0, fetched_at=now - timedelta(days=live_age_days))
    return merge_positions([flex], [live], {})[0]


def test_stale_overlay_defers_to_the_settled_snapshot():
    view = _merged(live_age_days=4)

    assert view.source == "settled"
    assert view.position == 2.0, "the newer snapshot's quantity wins"
    assert view.avg_cost == 77_260.0, "and its cost, normalized to multiplier-inclusive"
    assert view.live_unrealized is None, "no live P&L is computed off superseded data"


def test_fresh_overlay_still_wins():
    """Guards the over-correction: a current overlay is the whole point."""
    view = _merged(live_age_days=0)

    assert view.source == "live"
    assert view.position == 1.0
    assert view.avg_cost == 99_000.0


# ---------------------------------------------------------------------------
# Regression guard: the net-closed inference reads the account's *current* book.
#
# merge_positions drops a settled row when its account has live data, on the
# theory that a synced account which omits the instrument has netted it flat.
# That inference is only sound for a capture the snapshot has not superseded --
# a stale capture predates every position opened after it, so counting it makes
# each of those look closed. One stale overlay row was enough to hide every
# other holding in the account from the trade-group panel.
# ---------------------------------------------------------------------------

STALE_CAPTURE = datetime(2025, 1, 5, 23, 9, tzinfo=MT)
SNAPSHOT_AS_OF = date(2025, 1, 8)


def _account_book(*, capture_at: datetime):
    """An account holding two instruments, only one of which the capture saw.

    The second was opened after ``capture_at``, so it exists in the settled
    snapshot and is absent from the overlay -- the exact shape that the
    net-closed rule must not mistake for a close.
    """
    from src.services.intraday_overlay import merge_positions

    snapshot_at = datetime(2025, 1, 9, 9, 0, tzinfo=MT)
    held = _Row(con_id=1000000001, position=1.0, avg_cost=77.26, fetched_at=snapshot_at, as_of_date=SNAPSHOT_AS_OF)
    opened_after = _Row(con_id=1000000002, position=-1.0, avg_cost=90.37, fetched_at=snapshot_at, as_of_date=SNAPSHOT_AS_OF)
    live = _Row(con_id=1000000001, position=1.0, avg_cost=77_260.0, fetched_at=capture_at)
    views = merge_positions([held, opened_after], [live], {}, account_as_of={1: SNAPSHOT_AS_OF})
    return {v.con_id: v for v in views}


def test_superseded_capture_does_not_net_close_a_position_opened_after_it():
    views = _account_book(capture_at=STALE_CAPTURE)

    assert set(views) == {1000000001, 1000000002}, "the newer holding must survive the merge"
    assert views[1000000002].position == -1.0
    assert views[1000000002].source == "settled"


def test_current_capture_still_net_closes_an_instrument_it_omits():
    """Guards the over-correction: net-closing is the rule's whole purpose."""
    views = _account_book(capture_at=datetime(2025, 1, 9, 13, 0, tzinfo=MT))

    assert set(views) == {1000000001}, "a capture the snapshot has not superseded is authoritative"


def test_net_closing_falls_back_to_any_live_row_without_a_watermark():
    """No ``account_as_of`` (no settled snapshot to compare against) = prior behavior."""
    from src.services.intraday_overlay import merge_positions

    snapshot_at = datetime(2025, 1, 9, 9, 0, tzinfo=MT)
    held = _Row(con_id=1000000001, position=1.0, avg_cost=77.26, fetched_at=snapshot_at)
    gone = _Row(con_id=1000000002, position=-1.0, avg_cost=90.37, fetched_at=snapshot_at)
    live = _Row(con_id=1000000001, position=1.0, avg_cost=77_260.0, fetched_at=STALE_CAPTURE)

    views = merge_positions([held, gone], [live], {})

    assert {v.con_id for v in views} == {1000000001}
