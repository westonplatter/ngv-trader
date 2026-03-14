"""Worker heartbeat upsert helpers."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import WorkerHeartbeat

logger = logging.getLogger(__name__)

WORKER_TYPE_ORDERS = "orders"
WORKER_TYPE_JOBS = "jobs"

GREEN_SECONDS = 12.0
YELLOW_SECONDS = 30.0

_API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")


class WorkerStatusPayload(BaseModel):
    worker_type: str
    light: str
    status: str
    heartbeat_at: datetime | None
    seconds_since_heartbeat: float | None
    details: str | None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _classify_light(status: str, seconds_since: float | None) -> str:
    if status != "running":
        return "red"
    if seconds_since is None:
        return "red"
    if seconds_since <= GREEN_SECONDS:
        return "green"
    if seconds_since <= YELLOW_SECONDS:
        return "yellow"
    return "red"


def _notify_worker_status(worker_type: str) -> None:
    """Fire-and-forget notification to the API SSE broadcaster."""
    try:
        data = json.dumps({"worker_type": worker_type}).encode()
        req = urllib.request.Request(
            f"{_API_BASE_URL}/events/notify-worker-status",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2)
    except Exception as exc:
        logger.debug("SSE notify worker status failed: %s", exc)


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
    _notify_worker_status(worker_type)
