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

JOB_TYPE_POSITIONS_SYNC = "positions.sync"
JOB_TYPE_CONTRACTS_SYNC = "contracts.sync"
JOB_TYPE_WATCHLIST_ADD_INSTRUMENT = "watchlist.add_instrument"
JOB_TYPE_WATCHLIST_QUOTES_REFRESH = "watchlist.quotes_refresh"


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
