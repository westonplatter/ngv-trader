"""String vocabularies as ``StrEnum``.

Each member compares equal to, hashes like, and formats as its plain string, so
the DB columns stay ``String`` and existing literal comparisons keep working.
The values here are exactly what the database holds; changing one is a data
migration, not a refactor.
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Lifecycle of a ``jobs`` row."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OrderStatus(StrEnum):
    """Lifecycle of an ``orders`` row; transitions live in ``order_queue``."""

    QUEUED = "queued"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    RECONCILE_REQUIRED = "reconcile_required"


class ExecRole(StrEnum):
    """Role of a fill within a combo order (``exec_role`` on executions)."""

    COMBO_SUMMARY = "combo_summary"
    LEG = "leg"
    STANDALONE = "standalone"


class OverlaySource(StrEnum):
    """Which snapshot an intraday-overlay position row's numbers come from."""

    LIVE = "live"
    SETTLED = "settled"


class EntityType(StrEnum):
    """Item types that tags and tasks attach to (``entity_type`` on link rows)."""

    TRADE = "trade"
    TRADE_GROUP = "trade_group"
    TASK = "task"
    STRATEGY = "strategy"
    POSITION = "position"
    LIVE_EXECUTION = "live_execution"


class DataSource(StrEnum):
    """Where a synced row came from (``data_source`` columns)."""

    FLEX = "flex"
    TWS = "tws"
