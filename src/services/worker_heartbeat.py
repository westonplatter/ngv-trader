"""Worker heartbeat upsert helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import WorkerHeartbeat

WORKER_TYPE_ORDERS = "orders"
WORKER_TYPE_JOBS = "jobs"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def upsert_worker_heartbeat(
    engine: Engine,
    worker_type: str,
    status: str,
    details: str | None = None,
) -> None:
    heartbeat_at = now_utc()
    with Session(engine) as session:
        row = session.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_type == worker_type)).scalar_one_or_none()
        if row is None:
            row = WorkerHeartbeat(
                worker_type=worker_type,
                status=status,
                details=details,
                heartbeat_at=heartbeat_at,
                updated_at=heartbeat_at,
            )
            session.add(row)
        else:
            row.status = status
            row.details = details
            row.heartbeat_at = heartbeat_at
            row.updated_at = heartbeat_at
        session.commit()
