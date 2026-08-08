"""Retry cadence for FlexQuery fetches, as a function of the requested window.

A month-wide pull retried on the one-week cadence exhausts its attempt budget
before IBKR finishes building the statement, and enough wasted attempts earns a
``1025: Too many failed attempts`` lockout. These tests pin the rule that keeps
wide windows patient and narrow ones snappy.
"""

from src.services.flex_client_factory import (
    BASE_RETRY_DELAY_SECONDS,
    MAX_BACKOFF_SCALE,
    MAX_RETRY_DELAY_SECONDS,
    SHORT_RANGE_DAYS,
    backoff_scale,
    make_flex_client,
)


def test_unknown_span_keeps_short_range_cadence() -> None:
    assert backoff_scale(None) == 1.0


def test_windows_up_to_a_week_are_not_stretched() -> None:
    for span in (0, 1, SHORT_RANGE_DAYS):
        assert backoff_scale(span) == 1.0, f"span={span}"


def test_scale_grows_past_a_week() -> None:
    assert backoff_scale(SHORT_RANGE_DAYS + 1) > 1.0
    # A calendar month is roughly four weeks, so ~4x the one-week cadence.
    assert backoff_scale(30) == 30 / SHORT_RANGE_DAYS


def test_scale_is_monotonic_in_span() -> None:
    scales = [backoff_scale(span) for span in range(0, 400, 7)]
    assert scales == sorted(scales)


def test_scale_is_capped_so_one_fetch_cannot_run_for_hours() -> None:
    assert backoff_scale(3650) == MAX_BACKOFF_SCALE


def test_client_delays_reflect_the_span() -> None:
    weekly = make_flex_client(span_days=7)
    assert weekly.base_retry_delay == BASE_RETRY_DELAY_SECONDS
    assert weekly.max_retry_delay == MAX_RETRY_DELAY_SECONDS

    monthly = make_flex_client(span_days=31)
    assert monthly.base_retry_delay > weekly.base_retry_delay
    assert monthly.max_retry_delay > weekly.max_retry_delay


def test_client_without_a_span_matches_the_short_range_client() -> None:
    default = make_flex_client()
    weekly = make_flex_client(span_days=SHORT_RANGE_DAYS)
    assert default.base_retry_delay == weekly.base_retry_delay
    assert default.max_retry_delay == weekly.max_retry_delay
