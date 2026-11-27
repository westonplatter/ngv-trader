"""Orders API: the live order stream status."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import WorkerHeartbeat
from src.services.worker_heartbeat import WORKER_TYPE_ORDER_STREAM
from src.utils.time import now_utc

API = "/api/v1"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _heartbeat(db_session: Session, *, age_seconds: float, state: str, status: str = "running") -> str:
    beat_at = now_utc() - timedelta(seconds=age_seconds)
    last_event_at = (beat_at - timedelta(seconds=2)).isoformat()
    db_session.add(
        WorkerHeartbeat(
            worker_type=WORKER_TYPE_ORDER_STREAM,
            status=status,
            details=json.dumps({"state": state, "last_event_at": last_event_at, "client_id": 0}),
            heartbeat_at=beat_at,
            updated_at=beat_at,
        )
    )
    db_session.flush()
    return last_event_at


def test_fresh_live_heartbeat_reports_live_with_last_event(client: TestClient, db_session: Session) -> None:
    last_event_at = _heartbeat(db_session, age_seconds=3, state="live")

    body = client.get(f"{API}/orders/stream-status").json()

    assert body["state"] == "live"
    assert body["stream_state"] == "live"
    assert body["last_event_at"] is not None
    assert body["last_event_at"][:19] == last_event_at[:19]


def test_stale_heartbeat_reports_not_live(client: TestClient, db_session: Session) -> None:
    _heartbeat(db_session, age_seconds=120, state="live")

    assert client.get(f"{API}/orders/stream-status").json()["state"] == "not_live"


def test_reconnecting_stream_reports_not_live(client: TestClient, db_session: Session) -> None:
    _heartbeat(db_session, age_seconds=3, state="reconciling")

    body = client.get(f"{API}/orders/stream-status").json()

    assert body["state"] == "not_live"
    assert body["stream_state"] == "reconciling"


def test_stopped_stream_reports_not_live(client: TestClient, db_session: Session) -> None:
    _heartbeat(db_session, age_seconds=3, state="live", status="stopped")

    assert client.get(f"{API}/orders/stream-status").json()["state"] == "not_live"


def test_no_heartbeat_reports_disabled(client: TestClient) -> None:
    body = client.get(f"{API}/orders/stream-status").json()

    assert body == {
        "state": "disabled",
        "stream_state": None,
        "last_event_at": None,
        "heartbeat_at": None,
        "seconds_since_heartbeat": None,
    }
