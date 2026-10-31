"""Pure parsing of realized PnL from a raw execution payload.

Lives in the service layer (not an API router) so both the API routers and the
``trade_group_pnl`` service can use it without the service layer importing the
API layer — that edge caused a circular import that broke the MCP server on
startup (``src.services.trade_group_pnl`` -> ``src.api.routers.trades`` ->
``routers/__init__`` -> ``trade_groups`` -> back into ``trade_group_pnl``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, NamedTuple


class ExecutionPnlRow(NamedTuple):
    """The three columns the PnL and lifecycle rules read off a fill."""

    raw: dict | None
    exec_role: str | None
    is_canonical: bool


def execution_realized_pnl(raw: dict | None) -> float | None:
    """Realized PnL for one execution, from either the TWS or FlexQuery shape."""
    if not raw:
        return None

    # TWS shape: raw.commissionReport.realizedPNL (nested)
    commission_report = raw.get("commissionReport")
    if isinstance(commission_report, dict):
        value = commission_report.get("realizedPNL")
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                pass

    # FlexQuery shape: fifoPnlRealized at top level
    value = raw.get("fifoPnlRealized")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def realized_pnl_total(executions: Iterable[Any]) -> float | None:
    """Combo-aware realized PnL over a set of fills, for a trade, a trade group,
    or an account partition of either.

    ``executions`` are rows with ``raw`` and ``exec_role`` (``TradeExecution`` or
    :class:`ExecutionPnlRow`). A ``combo_summary`` row carries its spread's
    rolled-up realized PnL, so when any are present the total is those plus the
    standalone fills that are neither a combo summary nor one of its legs;
    otherwise every non-combo fill is summed. ``None`` when nothing contributes.

    Which rows to pass is the caller's scoping decision: a trade holds every
    revision of its fills, so the trades router passes canonical rows only; a
    trade group links to specific rows, so it passes exactly the linked ones.
    """
    rows = list(executions)
    combo_totals = [r for ex in rows if ex.exec_role == "combo_summary" for r in [execution_realized_pnl(ex.raw)] if r is not None]
    if combo_totals:
        standalone = [r for ex in rows if ex.exec_role not in {"combo_summary", "leg"} for r in [execution_realized_pnl(ex.raw)] if r is not None]
        return sum(combo_totals) + sum(standalone)

    values = [r for ex in rows if ex.exec_role != "combo_summary" for r in [execution_realized_pnl(ex.raw)] if r is not None]
    return sum(values) if values else None


_LIFECYCLE_BY_INDICATOR = {
    "O": "Open",
    "OPEN": "Open",
    "OPENING": "Open",
    "TOOPEN": "Open",
    "OPENPOSITION": "Open",
    "C": "Close",
    "CLOSE": "Close",
    "CLOSING": "Close",
    "TOCLOSE": "Close",
    "CLOSEPOSITION": "Close",
}


def execution_lifecycle(raw: dict | None) -> str | None:
    """``"Open"``/``"Close"`` for one fill from either raw shape, else ``None``.

    Same fields the Trades table reads: FlexQuery carries the indicator at the
    top level, TWS nests it under ``raw.execution``.
    """
    if not raw:
        return None
    candidates = [raw.get(field) for field in ("openCloseIndicator", "openClose", "positionEffect")]
    execution = raw.get("execution")
    if isinstance(execution, dict):
        candidates += [execution.get(field) for field in ("openClose", "positionEffect")]
    for value in candidates:
        lifecycle = _LIFECYCLE_BY_INDICATOR.get(str(value or "").strip().upper())
        if lifecycle is not None:
            return lifecycle
    return None
