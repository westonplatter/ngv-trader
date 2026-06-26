"""Stdio MCP server exposing the OSI semantic layer to external LLM agents.

Lets a CLI agent (e.g. Claude Code on a Mac) run business-analyst metrics by
*name* — it never writes SQL. This is the same path the in-app tradebot
``query_metric`` tool uses: the OSI model is the allow-list, the resolver compiles
a metric + dimensions + filters into one parameterized SELECT, and the executor
runs it read-only with a statement timeout.

Run it:
    uv run --extra mcp python -m src.mcp.semantic_server

Database connection (use a read-only role — see docs/core/semantic-queries.md):
    NGV_SEMANTIC_DATABASE_URL=postgresql://ngv_analyst:***@host:5432/ngtrader_prod
If unset, falls back to the app's DB_* environment variables.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from src.services.semantic.loader import get_model
from src.services.semantic.resolver import ALLOWED_TIME_GRAINS, build_metric_query
from src.services.semantic.executor import run_metric_query

mcp = FastMCP("ngv-semantic")


@lru_cache(maxsize=1)
def _get_engine() -> Engine:
    # Fail closed: require an explicit connection string so a misconfiguration
    # can't silently fall back to the app's read-write role. Point this at the
    # read-only ngv_analyst role (see docs/core/semantic-queries.md).
    url = os.environ.get("NGV_SEMANTIC_DATABASE_URL")
    if not url:
        raise RuntimeError("NGV_SEMANTIC_DATABASE_URL is required (use the read-only ngv_analyst role).")
    # Small pool; every query also runs in its own READ ONLY tx (see executor).
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2)


@mcp.tool()
def describe_semantic_model() -> dict[str, Any]:
    """Describe the available metrics and dimensions.

    Call this first to discover what you can query. Each metric names the grain
    ('fact') it lives on; a dimension is only valid for a metric if it is
    reachable from that metric's fact (the tool errors otherwise and names the
    valid options). Use these exact names with ``query_metric``.
    """
    model = get_model()
    metrics = []
    for m in model.metrics.values():
        valid_dims = sorted({name for ds in model.reachable(m.fact) for name in model.datasets[ds].dimensions})
        metrics.append(
            {
                "name": m.name,
                "grain": m.fact,
                "description": m.description,
                "synonyms": list(m.synonyms),
                "valid_dimensions": valid_dims,
            }
        )
    dimensions = [
        {
            "name": d.name,
            "dataset": d.dataset,
            "description": d.description,
            "synonyms": list(d.synonyms),
            "is_time": d.is_time,
        }
        for ds in model.datasets.values()
        for d in ds.dimensions.values()
    ]
    return {
        "metrics": metrics,
        "dimensions": dimensions,
        "time_grains": list(ALLOWED_TIME_GRAINS),
        "notes": "Filter by date range via start_date/end_date on the time axis. You cannot write SQL; pick names only.",
    }


@mcp.tool()
def query_metric(  # noqa: PLR0913 — tool params mirror the metric-query interface
    metric: str,
    group_by: list[str] | None = None,
    filters: dict[str, Any] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    time_grain: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Run a business-analyst metric over the trade database, read-only.

    Args:
        metric: Metric name (see describe_semantic_model), e.g. "realized_pnl".
        group_by: Dimension names to group by, e.g. ["symbol"].
        filters: Equality filters keyed by dimension name, e.g. {"symbol": "CL"}.
        start_date: ISO lower bound (inclusive) on the time dimension.
        end_date: ISO upper bound (inclusive) on the time dimension.
        time_grain: Bucket the time dimension when grouping by it
            (day, week, month, quarter, year).
        limit: Max rows (1-500).

    Returns the result rows and the compiled SQL (for auditing). Unknown
    metric/dimension/filter names raise an error listing the valid options.
    """
    model = get_model()
    query = build_metric_query(
        model,
        metric=metric,
        group_by=group_by or [],
        equality_filters=filters or {},
        date_start=start_date,
        date_end=end_date,
        time_grain=time_grain,
        limit=limit,
    )
    rows = run_metric_query(_get_engine(), query)
    return {
        "metric": query.metric,
        "group_by": list(query.group_by),
        "row_count": len(rows),
        "rows": rows,
        "sql": query.sql,
    }


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
