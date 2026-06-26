"""Compile a semantic-model selection into a single read-only SQL query.

The tradebot picks a metric, dimensions to group by, and filters *by name*; this
module turns that selection into one parameterized ``SELECT`` against the model's
fact source. All SQL fragments come from the trusted model YAML; every
caller-supplied value is bound as a parameter. There is no path for free-form SQL.

This is the Postgres analog of Snowflake's
``SELECT ... FROM SEMANTIC_VIEW(view DIMENSIONS ... METRICS ...)``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.services.semantic.loader import SemanticModel

ALLOWED_TIME_GRAINS = ("day", "week", "month", "quarter", "year")
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class MetricQuery:
    sql: str
    params: dict[str, Any]
    metric: str
    group_by: tuple[str, ...]


def _known(names: object) -> str:
    return ", ".join(sorted(names)) if names else "(none)"  # type: ignore[arg-type]


def build_metric_query(  # noqa: C901, PLR0912, PLR0913, PLR0915 — linear validate-then-build
    model: SemanticModel,
    *,
    metric: str,
    group_by: list[str] | None = None,
    equality_filters: dict[str, Any] | None = None,
    date_start: Any = None,
    date_end: Any = None,
    time_grain: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> MetricQuery:
    """Validate a selection against ``model`` and return a parameterized query.

    Raises ``ValueError`` (with the allowed names) on any unknown metric,
    dimension, filter key, or time grain so the tradebot can relay a useful
    correction to the model.
    """
    group_by = list(group_by or [])
    equality_filters = dict(equality_filters or {})

    if metric not in model.metrics:
        raise ValueError(f"Unknown metric '{metric}'. Available metrics: {_known(model.metrics)}.")

    for dim_name in group_by:
        if dim_name not in model.dimensions:
            raise ValueError(f"Unknown dimension '{dim_name}'. Available dimensions: {_known(model.dimensions)}.")
    # Preserve order, drop duplicates.
    group_by = list(dict.fromkeys(group_by))

    for key in equality_filters:
        if key not in model.dimensions:
            raise ValueError(f"Unknown filter '{key}'. Filterable dimensions: {_known(model.dimensions)}.")

    if time_grain is not None and time_grain not in ALLOWED_TIME_GRAINS:
        raise ValueError(f"Unknown time_grain '{time_grain}'. Allowed: {', '.join(ALLOWED_TIME_GRAINS)}.")

    if not isinstance(limit, int) or limit < 1 or limit > _MAX_LIMIT:
        raise ValueError(f"'limit' must be an integer between 1 and {_MAX_LIMIT}.")

    time_dim = model.time_dimension
    if (date_start is not None or date_end is not None) and time_dim is None:
        raise ValueError("This model has no time dimension; date filters are not supported.")

    params: dict[str, Any] = {}
    select_parts: list[str] = []
    group_parts: list[str] = []

    for dim_name in group_by:
        dim = model.dimensions[dim_name]
        alias = dim.name
        if not _IDENT_RE.match(alias):  # model is trusted, but never alias unsafely
            raise ValueError(f"Dimension name '{alias}' is not a safe SQL identifier.")
        if dim.is_time and time_grain is not None:
            expr = f"date_trunc(:time_grain, {dim.expression})"
            params["time_grain"] = time_grain
        else:
            expr = dim.expression
        select_parts.append(f"{expr} AS {alias}")
        group_parts.append(expr)

    metric_def = model.metrics[metric]
    if not _IDENT_RE.match(metric):
        raise ValueError(f"Metric name '{metric}' is not a safe SQL identifier.")
    select_parts.append(f"{metric_def.expression} AS {metric}")

    where_parts: list[str] = []
    for key, value in equality_filters.items():
        dim = model.dimensions[key]
        param = f"flt_{key}"
        where_parts.append(f"{dim.expression} = :{param}")
        params[param] = value

    if time_dim is not None:
        if date_start is not None:
            where_parts.append(f"{time_dim.expression} >= CAST(:date_start AS timestamptz)")
            params["date_start"] = date_start
        if date_end is not None:
            where_parts.append(f"{time_dim.expression} <= CAST(:date_end AS timestamptz)")
            params["date_end"] = date_end

    sql_lines = [
        f"SELECT {', '.join(select_parts)}",
        f"FROM {model.source} AS {model.dataset_name}",
    ]
    if where_parts:
        sql_lines.append("WHERE " + " AND ".join(where_parts))
    if group_parts:
        sql_lines.append("GROUP BY " + ", ".join(group_parts))
        sql_lines.append(f"ORDER BY {metric} DESC NULLS LAST")
    sql_lines.append("LIMIT :limit")
    params["limit"] = limit

    return MetricQuery(
        sql="\n".join(sql_lines),
        params=params,
        metric=metric,
        group_by=tuple(group_by),
    )
