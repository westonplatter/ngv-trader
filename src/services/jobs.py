"""Generic job queue primitives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Job

JOB_STATUS_QUEUED = "queued"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"


class JobDeferred(Exception):  # noqa: N818 — a control signal, not an error
    """A handler is not finished, but nothing has gone wrong: check back later.

    Raised when a job waits on something external that is merely slow — an IBKR
    Flex statement still being generated, say. The worker requeues the job after
    ``retry_after_seconds`` **without** counting an attempt: waiting is the
    expected path and must not consume the failure budget that exists for real
    errors. Handlers bound their own polling so a permanently stuck job still
    terminates.
    """

    def __init__(self, reason: str, retry_after_seconds: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


JOB_TYPE_POSITIONS_SYNC_TWS = "positions.sync.tws"
JOB_TYPE_POSITIONS_SYNC_FLEXQUERY = "positions.sync.flexquery"
JOB_TYPE_TRADES_SYNC_TWS = "trades.sync.tws"
# Kept as an entrypoint: enqueuing it fans out to one initiate_request per
# active token. The two phases below do the actual work.
JOB_TYPE_TRADES_SYNC_FLEXQUERY = "trades.sync.flexquery"
JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST = "trades.flexquery.initiate_request"
JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT = "trades.flexquery.fetch_report"
JOB_TYPE_CONTRACTS_SYNC = "contracts.sync"
JOB_TYPE_ORDER_SUBMIT = "order.submit"
JOB_TYPE_ORDER_FETCH_SYNC = "order.fetch_sync"
JOB_TYPE_ORDER_CANCEL = "order.cancel"
JOB_TYPE_WATCHLIST_ADD_INSTRUMENT = "watchlist.add_instrument"
JOB_TYPE_WATCHLIST_QUOTES_REFRESH = "watchlist.quotes_refresh"
JOB_TYPE_CONTRACTS_CHAIN_SYNC = "contracts.chain_sync"
JOB_TYPE_MARKET_DATA_FUTURES_PRICES = "market_data.futures_prices"
JOB_TYPE_MARKET_DATA_FUTURES_OPTIONS = "market_data.futures_options"
JOB_TYPE_MARKET_DATA_SNAPSHOT = "market_data.snapshot"
JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT = "contracts.qualify_and_snapshot"
JOB_TYPE_INTRADAY_SYNC_TWS = "intraday.sync.tws"
JOB_TYPE_OPTION_METRICS_SYNC_TWS = "option_metrics.sync.tws"
JOB_TYPE_CONTRACTS_SYNC_ACTIVATED = "contracts.sync_activated"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_job(
    session: Session,
    job_type: str,
    payload: dict,
    source: str,
    request_text: str | None,
    max_attempts: int = 3,
) -> Job:
    now = now_utc()
    job = Job(
        job_type=job_type,
        status=JOB_STATUS_QUEUED,
        payload=payload,
        result=None,
        source=source,
        request_text=request_text,
        attempts=0,
        max_attempts=max_attempts,
        available_at=now,
        created_at=now,
        updated_at=now,
        archived_at=None,
    )
    session.add(job)
    session.flush()
    return job


def enqueue_job_if_idle(
    session: Session,
    job_type: str,
    payload: dict,
    source: str,
    request_text: str | None,
    max_attempts: int = 3,
) -> Job | None:
    stmt = select(Job).where(
        Job.job_type == job_type,
        Job.archived_at.is_(None),
        Job.status.in_((JOB_STATUS_QUEUED, JOB_STATUS_RUNNING)),
    )
    active = session.execute(stmt).scalars().first()
    if active is not None:
        return None
    return enqueue_job(
        session=session,
        job_type=job_type,
        payload=payload,
        source=source,
        request_text=request_text,
        max_attempts=max_attempts,
    )


def claim_next_job(session: Session) -> Job | None:
    now = now_utc()
    stmt = (
        select(Job)
        .where(
            Job.status == JOB_STATUS_QUEUED,
            Job.available_at <= now,
            Job.archived_at.is_(None),
        )
        .order_by(Job.created_at.asc())
        .limit(1)
    )
    job = session.execute(stmt).scalars().first()
    if job is None:
        return None
    job.status = JOB_STATUS_RUNNING
    job.started_at = now
    job.updated_at = now
    session.flush()
    return job


def complete_job(session: Session, job: Job, result: dict) -> None:
    now = now_utc()
    job.status = JOB_STATUS_COMPLETED
    job.result = result
    job.completed_at = now
    job.updated_at = now
    session.flush()


def defer_job(session: Session, job: Job, reason: str, retry_after_seconds: int) -> None:
    """Requeue a job to run later without recording a failure.

    Unlike ``fail_or_retry_job`` this leaves ``attempts`` untouched, so a job
    that legitimately waits on a slow external system keeps its full retry
    budget for actual errors.
    """
    now = now_utc()
    job.status = JOB_STATUS_QUEUED
    job.available_at = now + timedelta(seconds=retry_after_seconds)
    job.last_error = reason
    job.updated_at = now
    session.flush()


def fail_or_retry_job(session: Session, job: Job, error_text: str, retry_delay_seconds: int = 5) -> None:
    now = now_utc()
    job.attempts += 1
    job.last_error = error_text
    job.updated_at = now

    if job.attempts >= job.max_attempts:
        job.status = JOB_STATUS_FAILED
        job.completed_at = now
    else:
        job.status = JOB_STATUS_QUEUED
        job.available_at = now + timedelta(seconds=retry_delay_seconds)
    session.flush()
