"""SSE streaming endpoint and worker notification hooks for real-time UI updates."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db

DB_SESSION_DEPENDENCY = Depends(get_db)

from src.api.routers.jobs import to_job_response
from src.api.routers.orders import to_order_response
from src.models import Account, ContractRef, Job, Order, WorkerHeartbeat
from src.services.ui_events import (
    TOPIC_JOBS,
    TOPIC_ORDERS,
    TOPIC_WORKER_STATUS,
    broadcaster,
    make_event,
)
from src.services.worker_heartbeat import WorkerStatusPayload, _classify_light

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/events/stream", response_class=EventSourceResponse)
async def stream_events(
    topics: str = "jobs,orders,worker_status",
) -> AsyncIterable[ServerSentEvent]:
    topic_list = [t.strip() for t in topics.split(",") if t.strip()]
    subscriber = broadcaster.subscribe(topic_list)
    logger.info("SSE stream opened: topics=%s", topic_list)
    try:
        async for event in subscriber:
            yield ServerSentEvent(
                data=event.model_dump(mode="json"),
                event=event.event,
            )
    finally:
        broadcaster.unsubscribe(subscriber)
        logger.info("SSE stream closed")


# ---------------------------------------------------------------------------
# Worker notification endpoints
#
# The job worker runs in a separate process and cannot access the in-memory
# broadcaster directly.  After committing a state change the worker POSTs
# the entity id here so the API process can build the response DTO and
# push it to SSE subscribers.
# ---------------------------------------------------------------------------


class NotifyJobRequest(BaseModel):
    job_id: int
    event: str = "job.updated"


class NotifyOrderRequest(BaseModel):
    order_id: int
    event: str = "order.updated"


@router.post("/events/notify-job", status_code=204)
def notify_job(
    body: NotifyJobRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> None:
    job = db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    resp = to_job_response(job)
    broadcaster.publish(make_event(TOPIC_JOBS, body.event, resp, entity_id=job.id))


class NotifyWorkerStatusRequest(BaseModel):
    worker_type: str


@router.post("/events/notify-worker-status", status_code=204)
def notify_worker_status(
    body: NotifyWorkerStatusRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> None:
    row = db.execute(select(WorkerHeartbeat).where(WorkerHeartbeat.worker_type == body.worker_type)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Worker not found")
    now = datetime.now(timezone.utc)
    seconds_since = max(0.0, (now - row.heartbeat_at).total_seconds())
    payload = WorkerStatusPayload(
        worker_type=row.worker_type,
        light=_classify_light(row.status, seconds_since),
        status=row.status,
        heartbeat_at=row.heartbeat_at,
        seconds_since_heartbeat=seconds_since,
        details=row.details,
    )
    broadcaster.publish(make_event(TOPIC_WORKER_STATUS, "worker.heartbeat", payload))


@router.post("/events/notify-order", status_code=204)
def notify_order(
    body: NotifyOrderRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> None:
    stmt = (
        select(Order, Account, ContractRef)
        .outerjoin(Account, Order.account_id == Account.id)
        .outerjoin(ContractRef, Order.con_id == ContractRef.con_id)
        .where(Order.id == body.order_id)
    )
    row = db.execute(stmt).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    order, account, contract_ref = row
    resp = to_order_response(order, account, contract_ref)
    broadcaster.publish(make_event(TOPIC_ORDERS, body.event, resp, entity_id=order.id))
