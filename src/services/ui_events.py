"""In-memory async pub/sub broker for SSE UI events.

Provides a lightweight event broadcaster that fans out typed events to
subscriber queues, keyed by topic.  Designed for single-process deployment.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------

TOPIC_JOBS = "jobs"
TOPIC_ORDERS = "orders"
TOPIC_WORKER_STATUS = "worker_status"


class UIEvent(BaseModel):
    """Wire envelope for all SSE events."""

    topic: str
    event: str
    entity_id: int | None = None
    occurred_at: datetime
    version: int = 1
    payload: dict[str, Any]


def make_event(
    topic: str,
    event: str,
    payload: BaseModel,
    entity_id: int | None = None,
) -> UIEvent:
    """Build an envelope from a Pydantic response DTO."""
    return UIEvent(
        topic=topic,
        event=event,
        entity_id=entity_id,
        occurred_at=datetime.now(timezone.utc),
        payload=payload.model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Subscriber handle
# ---------------------------------------------------------------------------

MAX_QUEUE_SIZE = 256


class Subscriber:
    """A single SSE client subscription with its own async queue."""

    __slots__ = ("topics", "queue")

    def __init__(self, topics: set[str]) -> None:
        self.topics = topics
        self.queue: asyncio.Queue[UIEvent] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)

    def __aiter__(self):
        return self

    async def __anext__(self) -> UIEvent:
        return await self.queue.get()


# ---------------------------------------------------------------------------
# Broadcaster singleton
# ---------------------------------------------------------------------------


class Broadcaster:
    """In-memory async fan-out broker."""

    def __init__(self) -> None:
        self._subscribers: set[Subscriber] = set()

    def subscribe(self, topics: list[str]) -> Subscriber:
        sub = Subscriber(topics=set(topics))
        self._subscribers.add(sub)
        logger.info("SSE subscriber added: topics=%s  total=%d", topics, len(self._subscribers))
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)
        logger.info("SSE subscriber removed: total=%d", len(self._subscribers))

    def publish(self, event: UIEvent) -> None:
        """Push an event into all matching subscriber queues.

        Slow subscribers whose queues are full are dropped (the SSE
        connection will be closed so the browser can reconnect and
        re-snapshot via REST).
        """
        to_drop: list[Subscriber] = []
        for sub in self._subscribers:
            if event.topic not in sub.topics:
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropping slow SSE subscriber (queue full, topic=%s)", event.topic)
                to_drop.append(sub)
        for sub in to_drop:
            self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


# Module-level singleton used by publish hooks and the SSE endpoint.
broadcaster = Broadcaster()
