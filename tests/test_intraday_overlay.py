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
