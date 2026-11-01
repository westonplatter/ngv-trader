"""The enums must hold exactly the strings the database stores."""

from __future__ import annotations

from enum import StrEnum

import pytest

from src import models
from src.domain.enums import DataSource, EntityType, ExecRole, JobStatus, OrderStatus, OverlaySource
from src.services import jobs, order_queue

ENUM_VALUES: list[tuple[type[StrEnum], dict[str, str]]] = [
    (JobStatus, {"QUEUED": "queued", "RUNNING": "running", "COMPLETED": "completed", "FAILED": "failed"}),
    (
        OrderStatus,
        {
            "QUEUED": "queued",
            "SUBMITTING": "submitting",
            "SUBMITTED": "submitted",
            "PARTIALLY_FILLED": "partially_filled",
            "FILLED": "filled",
            "CANCELLED": "cancelled",
            "REJECTED": "rejected",
            "FAILED": "failed",
            "RECONCILE_REQUIRED": "reconcile_required",
        },
    ),
    (ExecRole, {"COMBO_SUMMARY": "combo_summary", "LEG": "leg", "STANDALONE": "standalone"}),
    (OverlaySource, {"LIVE": "live", "SETTLED": "settled"}),
    (
        EntityType,
        {
            "TRADE": "trade",
            "TRADE_GROUP": "trade_group",
            "TASK": "task",
            "STRATEGY": "strategy",
            "POSITION": "position",
            "LIVE_EXECUTION": "live_execution",
        },
    ),
    (DataSource, {"FLEX": "flex", "TWS": "tws"}),
]


@pytest.mark.parametrize(("enum_cls", "expected"), ENUM_VALUES, ids=[cls.__name__ for cls, _ in ENUM_VALUES])
def test_enum_values_are_the_db_strings(enum_cls: type[StrEnum], expected: dict[str, str]) -> None:
    assert {member.name: member.value for member in enum_cls} == expected
    for name, value in expected.items():
        member = enum_cls[name]
        assert member == value
        assert str(member) == value
        assert enum_cls(value) is member
        assert hash(member) == hash(value)


def test_module_constants_keep_their_string_values() -> None:
    assert (jobs.JOB_STATUS_QUEUED, jobs.JOB_STATUS_RUNNING, jobs.JOB_STATUS_COMPLETED, jobs.JOB_STATUS_FAILED) == (
        "queued",
        "running",
        "completed",
        "failed",
    )
    for member in OrderStatus:
        assert getattr(order_queue, f"ORDER_STATUS_{member.name}") == member.value
    assert order_queue.ORDER_TERMINAL_STATUSES == {"filled", "cancelled", "rejected", "failed"}
    assert set(order_queue.ALLOWED_ORDER_STATUS_TRANSITIONS) == {m.value for m in OrderStatus}


def test_model_entity_type_tuples_are_derived_from_the_enum() -> None:
    assert models.TAG_ENTITY_TYPES == ("trade", "live_execution", "position", "trade_group", "task")
    assert models.TASK_ENTITY_TYPES == ("strategy", "trade_group", "position", "trade", "live_execution")
    assert set(models.TAG_ENTITY_TYPES) | set(models.TASK_ENTITY_TYPES) == {m.value for m in EntityType}
