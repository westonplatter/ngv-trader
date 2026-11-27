"""Jobs worker: order notifications and the order.fetch_sync client ID."""

from __future__ import annotations

import importlib.util
import urllib.error
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.engine import Engine

from src.models import Job
from src.services import order_sync_tws
from src.services.jobs import (
    JOB_TYPE_ORDER_FETCH_SYNC,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
)
from src.workers import jobs as worker_jobs
from src.workers.jobs import IBSessionPool


def _load_work_jobs() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "scripts" / "work_jobs.py"
    spec = importlib.util.spec_from_file_location("work_jobs_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


work_jobs = _load_work_jobs()


def _record_posts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    posts: list[tuple[str, dict]] = []
    monkeypatch.setattr(work_jobs, "_notify_api", lambda path, payload: posts.append((path, payload)))
    return posts


def test_notifies_each_changed_order_with_its_event(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _record_posts(monkeypatch)

    work_jobs._notify_orders_for_job(JOB_TYPE_ORDER_FETCH_SYNC, {"created_order_ids": [5, 6], "updated_order_ids": [7]})

    assert posts == [
        ("/events/notify-order", {"order_id": 5, "event": "order.created"}),
        ("/events/notify-order", {"order_id": 6, "event": "order.created"}),
        ("/events/notify-order", {"order_id": 7, "event": "order.updated"}),
    ]


def test_posts_nothing_when_nothing_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _record_posts(monkeypatch)

    work_jobs._notify_orders_for_job(JOB_TYPE_ORDER_FETCH_SYNC, {"created_order_ids": [], "updated_order_ids": []})
    work_jobs._notify_orders_for_job(JOB_TYPE_ORDER_FETCH_SYNC, {})
    work_jobs._notify_orders_for_job(JOB_TYPE_ORDER_FETCH_SYNC, None)

    assert posts == []


def test_other_job_types_post_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _record_posts(monkeypatch)

    work_jobs._notify_orders_for_job(JOB_TYPE_POSITIONS_SYNC_FLEXQUERY, {"created_order_ids": [5]})

    assert posts == []


@pytest.mark.parametrize("failure", [urllib.error.URLError("refused"), TimeoutError("timed out")])
def test_a_failed_post_is_logged_and_does_not_stop_the_rest(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    attempts: list[int] = []

    def flaky(path: str, payload: dict) -> None:
        attempts.append(payload["order_id"])
        raise failure

    monkeypatch.setattr(work_jobs, "_notify_api", flaky)

    work_jobs._notify_orders_for_job(JOB_TYPE_ORDER_FETCH_SYNC, {"created_order_ids": [5], "updated_order_ids": [7]})

    assert attempts == [5, 7]


class _FakePool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return object()


def _run_handler(monkeypatch: pytest.MonkeyPatch, payload: dict) -> dict[str, Any]:
    pool = _FakePool()
    monkeypatch.setattr(
        order_sync_tws,
        "sync_orders_with_ib",
        lambda engine, *, ib: {"fetched_trades_count": 0, "created_order_ids": [], "updated_order_ids": []},
    )
    job = cast(Job, SimpleNamespace(payload=payload))
    worker_jobs.handle_order_fetch_sync(job, cast(Engine, object()), cast(IBSessionPool, pool))
    return pool.calls[0]


def test_order_fetch_sync_connects_with_its_own_client_id(monkeypatch: pytest.MonkeyPatch) -> None:
    call = _run_handler(monkeypatch, {"port": 7497})

    assert call["client_id"] == worker_jobs.ORDER_FETCH_SYNC_CLIENT_ID
    assert call["client_id"] != 0


def test_order_fetch_sync_honors_a_client_id_in_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    call = _run_handler(monkeypatch, {"port": 7497, "client_id": 55})

    assert call["client_id"] == 55
