"""Two-phase FlexQuery fetch: the wait ladder and the job deferral primitive."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from src.models import Job
from src.services.flex_client_factory import (
    FIRST_CHECK_FALLBACK_SECONDS,
    SHORT_RANGE_DAYS,
    first_check_delay_seconds,
)
from src.services.jobs import (
    JOB_STATUS_QUEUED,
    JobDeferred,
    defer_job,
    enqueue_job,
    fail_or_retry_job,
)


@pytest.mark.parametrize(
    ("span_days", "expected"),
    [(1, 20), (SHORT_RANGE_DAYS, 20), (8, 60), (31, 60), (32, 120), (92, 120), (365, FIRST_CHECK_FALLBACK_SECONDS)],
)
def test_first_check_ladder(span_days: int, expected: int) -> None:
    assert first_check_delay_seconds(span_days) == expected


def test_windows_wider_than_a_week_wait_at_least_a_minute() -> None:
    """The floor that keeps a 1001 from escalating into a 1025 lockout."""
    for span in (SHORT_RANGE_DAYS + 1, 30, 90, 400):
        assert first_check_delay_seconds(span) >= 60


def test_unknown_span_is_the_most_patient() -> None:
    assert first_check_delay_seconds(None) == FIRST_CHECK_FALLBACK_SECONDS


def _queue(session: Session) -> Job:
    job = enqueue_job(
        session=session,
        job_type="trades.flexquery.fetch_report",
        payload={"checks": 0},
        source="test",
        request_text=None,
    )
    job.status = "running"
    session.flush()
    return job


def test_defer_requeues_without_spending_an_attempt(db_session: Session) -> None:
    job = _queue(db_session)
    before = datetime.now(timezone.utc)

    defer_job(db_session, job, "statement not ready", 30)

    assert job.status == JOB_STATUS_QUEUED
    assert job.attempts == 0
    assert job.available_at >= before + timedelta(seconds=29)
    assert job.last_error == "statement not ready"


def test_defer_is_unbounded_where_failure_is_not(db_session: Session) -> None:
    """A slow statement must not exhaust the budget reserved for real errors."""
    job = _queue(db_session)
    for _ in range(job.max_attempts + 5):
        defer_job(db_session, job, "still building", 30)
    assert job.attempts == 0
    assert job.status == JOB_STATUS_QUEUED

    # A genuine failure still consumes the budget and terminates.
    for _ in range(job.max_attempts):
        fail_or_retry_job(db_session, job, "boom")
    assert job.status == "failed"


def test_job_deferred_carries_its_delay() -> None:
    exc = JobDeferred("not ready", 45)
    assert exc.retry_after_seconds == 45
    assert exc.reason == "not ready"
    assert "not ready" in str(exc)


# ── Token pause window ────────────────────────────────────────────────────────


def test_rate_limit_error_is_recognized_from_the_flattened_message() -> None:
    """The client folds the error code into the text before it reaches us."""
    from src.services.flex_credentials import is_rate_limit_error

    assert is_rate_limit_error(RuntimeError("Failed after 1 attempts: 1025: Too many failed attempts."))
    assert not is_rate_limit_error(RuntimeError("1001: Statement could not be generated at this time."))


def test_pause_remaining_counts_down_and_floors_at_zero() -> None:
    from src.services.flex_credentials import FlexCredential

    now = datetime.now(timezone.utc)
    usable = FlexCredential(token_id=1, name="lp", token="t", report_id="1", paused_until=None)
    paused = FlexCredential(token_id=1, name="lp", token="t", report_id="1", paused_until=now + timedelta(minutes=20))
    expired = FlexCredential(token_id=1, name="lp", token="t", report_id="1", paused_until=now - timedelta(minutes=1))

    assert usable.pause_remaining_seconds(now) == 0
    assert 1190 <= paused.pause_remaining_seconds(now) <= 1200
    assert expired.pause_remaining_seconds(now) == 0
