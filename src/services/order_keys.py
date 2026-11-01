"""Order group key shared by the intraday sync, live reconcile, and the trades API.

A combo order arrives as one BAG summary fill plus one fill per leg; the order
key ties them together. ``permId`` is stable across the order lifecycle and is
preferred; ``orderId`` is the fallback. ``None`` means the fill carries neither,
so it is never grouped.

Two entry points differ only in input shape: a raw ``ib_async`` execution
(camelCase attributes, values that may be floats) and a stored ``LiveExecution``
row (``ib_perm_id`` / ``ib_order_id`` columns).
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Any

from src.models import LiveExecution

OrderGroupKey = tuple[str, int]


def _as_int(value: object) -> int | None:
    """Coerce a finite real number to ``int``; anything else is ``None``."""
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return int(parsed)


def _group_key(perm_id: int | None, order_id: int | None) -> OrderGroupKey | None:
    if perm_id:
        return ("perm", perm_id)
    if order_id:
        return ("order", order_id)
    return None


def order_group_key_from_execution(execution: Any) -> OrderGroupKey | None:
    """Key for an ``ib_async`` execution (``permId`` preferred, else ``orderId``)."""
    return _group_key(_as_int(getattr(execution, "permId", None)), _as_int(getattr(execution, "orderId", None)))


def order_group_key_from_live(live: LiveExecution) -> OrderGroupKey | None:
    """Key for a stored live fill (``ib_perm_id`` preferred, else ``ib_order_id``)."""
    return _group_key(live.ib_perm_id, live.ib_order_id)
