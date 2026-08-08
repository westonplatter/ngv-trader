"""Shared factory for `FlexClient` so all sync paths use the same retry/backoff.

Large date ranges (multi-month reimports) push IBKR's statement generation past
the default retry budget. Bump max_retries, base/max delays, and the initial
poll wait so 180-day pulls survive without manual reruns.

Retry delays additionally scale with the width of the requested window — see
`backoff_scale`.
"""

from __future__ import annotations

from ngv_reports_ibkr.flex_client import FlexClient

# Windows this wide or narrower need no extra patience — IBKR builds them quickly.
SHORT_RANGE_DAYS = 7
# Ceiling on the multiplier so a multi-year pull cannot stretch one fetch to hours.
MAX_BACKOFF_SCALE = 6.0

BASE_RETRY_DELAY_SECONDS = 2.0
MAX_RETRY_DELAY_SECONDS = 120.0
STATEMENT_POLL_DELAY_SECONDS = 5.0


def backoff_scale(span_days: int | None) -> float:
    """How much to stretch retry delays for a window of ``span_days``.

    IBKR takes longer to build a statement the wider the window, and answers
    ``1001: Statement could not be generated at this time`` while it works.
    Retrying a month-wide pull on the one-week cadence just burns the attempt
    budget before the statement is ready — and enough wasted attempts earns a
    ``1025: Too many failed attempts`` lockout that outlives the job. So past a
    week, back off in proportion to how much wider the window is.
    """
    if span_days is None or span_days <= SHORT_RANGE_DAYS:
        return 1.0
    return min(span_days / SHORT_RANGE_DAYS, MAX_BACKOFF_SCALE)


# How long to wait before first asking IBKR whether a statement is ready, by
# window width. Grounded in real runs — a month-wide pull completes in ~22s end
# to end — so these are patience budgets, not work estimates. The floor above a
# week is deliberate: checking a wide window too eagerly is what turns
# ``1001: Statement could not be generated`` into a ``1025`` lockout.
FIRST_CHECK_LADDER: tuple[tuple[int, int], ...] = (
    (SHORT_RANGE_DAYS, 20),
    (31, 60),
    (92, 120),
)
FIRST_CHECK_FALLBACK_SECONDS = 180
# Gap between later checks once the first finds the statement still building.
RECHECK_DELAY_SECONDS = 30
# Stop checking eventually so a statement that never lands still terminates.
MAX_STATEMENT_CHECKS = 20


def first_check_delay_seconds(span_days: int | None) -> int:
    """Seconds to wait after sending a request before the first readiness check."""
    if span_days is None:
        return FIRST_CHECK_FALLBACK_SECONDS
    for max_days, delay in FIRST_CHECK_LADDER:
        if span_days <= max_days:
            return delay
    return FIRST_CHECK_FALLBACK_SECONDS


def make_flex_client(span_days: int | None = None, max_retries: int = 10) -> FlexClient:
    """A client tuned for a fetch covering ``span_days``.

    Pass the width of the date range being requested; omit it only when the
    window is unknown, which keeps the short-range cadence.

    Lower ``max_retries`` when the *caller* owns the waiting — the two-phase
    job flow reschedules itself between checks, so it wants the client to
    surface "not ready" immediately rather than block a worker slot sleeping
    through an internal retry loop.
    """
    scale = backoff_scale(span_days)
    return FlexClient(
        max_retries=max_retries,
        base_retry_delay=BASE_RETRY_DELAY_SECONDS * scale,
        max_retry_delay=MAX_RETRY_DELAY_SECONDS * scale,
        statement_poll_delay=STATEMENT_POLL_DELAY_SECONDS * scale,
    )
