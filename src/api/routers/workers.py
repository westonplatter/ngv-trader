"""Workers API router."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import WorkerHeartbeat
from src.services.worker_heartbeat import WORKER_TYPE_JOBS, WORKER_TYPE_ORDERS

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

GREEN_SECONDS = 12.0
YELLOW_SECONDS = 30.0


class WorkerStatusResponse(BaseModel):
    worker_type: str
    light: str
    status: str
    heartbeat_at: datetime | None
    seconds_since_heartbeat: float | None
    details: str | None


def classify_light(status: str, seconds_since_heartbeat: float | None) -> str:
    if status != "running":
        return "red"
    if seconds_since_heartbeat is None:
        return "red"
    if seconds_since_heartbeat <= GREEN_SECONDS:
        return "green"
    if seconds_since_heartbeat <= YELLOW_SECONDS:
        return "yellow"
    return "red"


def to_response(now: datetime, row: WorkerHeartbeat | None, worker_type: str) -> WorkerStatusResponse:
    if row is None:
        return WorkerStatusResponse(
            worker_type=worker_type,
            light="red",
            status="unknown",
            heartbeat_at=None,
            seconds_since_heartbeat=None,
            details="No heartbeat received yet.",
        )

    seconds_since = max(0.0, (now - row.heartbeat_at).total_seconds())
    return WorkerStatusResponse(
        worker_type=worker_type,
        light=classify_light(row.status, seconds_since),
        status=row.status,
        heartbeat_at=row.heartbeat_at,
        seconds_since_heartbeat=seconds_since,
        details=row.details,
    )


@router.get("/workers/status", response_model=list[WorkerStatusResponse])
def list_worker_statuses(
    db: Session = DB_SESSION_DEPENDENCY,
) -> list[WorkerStatusResponse]:
    rows = db.execute(select(WorkerHeartbeat)).scalars().all()
    by_type = {row.worker_type: row for row in rows}
    now = datetime.now(timezone.utc)
    worker_types = [WORKER_TYPE_ORDERS, WORKER_TYPE_JOBS]
    return [to_response(now, by_type.get(worker_type), worker_type) for worker_type in worker_types]
