"""Pure parsing of realized PnL from a raw execution payload.

Lives in the service layer (not an API router) so both the API routers and the
``trade_group_pnl`` service can use it without the service layer importing the
API layer — that edge caused a circular import that broke the MCP server on
startup (``src.services.trade_group_pnl`` -> ``src.api.routers.trades`` ->
``routers/__init__`` -> ``trade_groups`` -> back into ``trade_group_pnl``).
"""

from __future__ import annotations


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
