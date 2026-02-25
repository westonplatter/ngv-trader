"""Jobs API router."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Job
from src.services.jobs import now_utc

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class JobResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    job_type: str
    status: str
    payload: dict
    result: dict | None
    source: str
    request_text: str | None
    attempts: int
    max_attempts: int
    available_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    archived_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


def to_job_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        source=job.source,
        request_text=job.request_text,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        available_at=job.available_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        archived_at=job.archived_at,
        last_error=job.last_error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    include_archived: bool = Query(default=False),
    db: Session = DB_SESSION_DEPENDENCY,
) -> list[JobResponse]:
    stmt = select(Job)
    if not include_archived:
        stmt = stmt.where(Job.archived_at.is_(None))
    rows = db.execute(stmt.order_by(Job.created_at.desc())).scalars().all()
    return [to_job_response(job) for job in rows]


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = DB_SESSION_DEPENDENCY) -> JobResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return to_job_response(job)


@router.post("/jobs/{job_id}/archive", response_model=JobResponse)
def archive_job(job_id: int, db: Session = DB_SESSION_DEPENDENCY) -> JobResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.archived_at is None:
        now = now_utc()
        job.archived_at = now
        job.updated_at = now
        db.commit()
        db.refresh(job)
    return to_job_response(job)
