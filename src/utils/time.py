"""Clock helpers shared by services, routers, and workers."""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    """The current time as an aware UTC ``datetime``."""
    return datetime.now(timezone.utc)
