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
