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


# ── Handler wiring ────────────────────────────────────────────────────────────


def test_both_domains_register_all_three_phases() -> None:
    """Trades and positions must stay symmetric — a missing phase strands jobs."""
    from src.services.jobs import (
        JOB_TYPE_POSITIONS_FLEXQUERY_FETCH_REPORT,
        JOB_TYPE_POSITIONS_FLEXQUERY_INITIATE_REQUEST,
        JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
        JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
        JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST,
        JOB_TYPE_TRADES_SYNC_FLEXQUERY,
    )
    from src.workers.jobs import get_handler

    for job_type in (
        JOB_TYPE_TRADES_SYNC_FLEXQUERY,
        JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST,
        JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
        JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
        JOB_TYPE_POSITIONS_FLEXQUERY_INITIATE_REQUEST,
        JOB_TYPE_POSITIONS_FLEXQUERY_FETCH_REPORT,
    ):
        assert get_handler(job_type) is not None, job_type


def test_position_window_defaults_to_a_single_day() -> None:
    """An EOD snapshot wants one day; trades want a trailing span."""
    from src.workers.jobs import _flexquery_window

    pos_start, pos_end = _flexquery_window({}, default_days=0)
    assert pos_start == pos_end

    trade_start, trade_end = _flexquery_window({})
    assert (trade_end - trade_start).days == 7


def test_explicit_dates_override_the_default_in_both_domains() -> None:
    from src.workers.jobs import _flexquery_window

    payload = {"start_date": "2026-06-01", "end_date": "2026-06-30"}
    for default_days in (0, 7):
        start, end = _flexquery_window(payload, default_days)
        assert start.isoformat() == "2026-06-01"
        assert end.isoformat() == "2026-06-30"


# ── Paused tokens make no IBKR calls ──────────────────────────────────────────


def _paused_credential(seconds: int = 900):
    from src.services.flex_credentials import FlexCredential

    return FlexCredential(
        token_id=3,
        name="lp",
        token="secret",  # noqa: S106  # nosec B106 — fixture value
        report_id="656962",
        paused_until=datetime.now(timezone.utc) + timedelta(seconds=seconds),
    )


@pytest.mark.parametrize(
    "handler_name",
    ["handle_trades_flexquery_initiate_request", "handle_positions_flexquery_initiate_request"],
)
def test_initiate_defers_without_contacting_ibkr_while_paused(monkeypatch: pytest.MonkeyPatch, handler_name: str) -> None:
    """An unchecked send earns another 1025 and slides the cooldown forward."""
    import src.services.flex_client_factory as factory
    import src.workers.jobs as workers

    monkeypatch.setattr(workers, "load_credential_by_id", lambda engine, token_id: _paused_credential())

    def _explode(*args, **kwargs):
        raise AssertionError("a paused token must not build a Flex client")

    monkeypatch.setattr(factory, "make_flex_client", _explode)

    job = Job(job_type="x", payload={"token_id": 3, "start_date": "2026-08-07", "end_date": "2026-08-07"})

    with pytest.raises(JobDeferred) as excinfo:
        getattr(workers, handler_name)(job, None, None)

    assert "paused" in excinfo.value.reason
    assert 0 < excinfo.value.retry_after_seconds <= 900


def test_fetch_report_also_defers_while_paused(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.services.flex_client_factory as factory
    import src.workers.jobs as workers

    monkeypatch.setattr(workers, "load_credential_by_id", lambda engine, token_id: _paused_credential())

    def _explode(*args, **kwargs):
        raise AssertionError("a paused token must not build a Flex client")

    monkeypatch.setattr(factory, "make_flex_client", _explode)

    job = Job(
        job_type="x",
        payload={"token_id": 3, "reference_code": "1000000001", "start_date": "2026-08-07", "end_date": "2026-08-07"},
    )

    with pytest.raises(JobDeferred):
        workers.handle_trades_flexquery_fetch_report(job, None, None)
