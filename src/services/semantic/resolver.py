"""Compile a semantic-model selection into a single read-only SQL query.

The agent picks a metric, dimensions, and filters *by name*. This module routes
the query to the metric's fact dataset, resolves each dimension to the nearest
dataset reachable from that fact, joins in only what's referenced (walking the
relationship graph), and emits one parameterized ``SELECT``. All SQL fragments
come from the trusted model; every caller value is bound. There is no free-form
SQL path.

One grain per query: a dimension that isn't reachable from the metric's fact is
rejected (e.g. an option strike against a trade-grain metric). See
docs/core/semantic-queries.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.services.semantic.loader import Dimension, SemanticModel

ALLOWED_TIME_GRAINS = ("day", "week", "month", "quarter", "year")
_MAX_LIMIT = 500
_DEFAULT_LIMIT = 50
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class MetricQuery:
    sql: str
    params: dict[str, Any]
    metric: str
    fact: str
    group_by: tuple[str, ...]


def _safe_alias(name: str, *, kind: str) -> str:
    if not _IDENT_RE.match(name):
        raise ValueError(f"{kind} name '{name}' is not a safe SQL identifier.")
    return name


def _join_clauses(model: SemanticModel, fact: str, used_datasets: set[str]) -> list[str]:
    """LEFT JOINs needed to reach ``used_datasets`` from ``fact``, in dependency order."""
    needed_rel_by_target: dict[str, Any] = {}
    for ds in used_datasets:
        if ds == fact:
            continue
        path = model.join_path(fact, ds)
        if path is None:
            raise ValueError(f"Dimension dataset '{ds}' is not reachable from fact '{fact}'.")
        for rel in path:
            needed_rel_by_target[rel.to_dataset] = rel

    clauses: list[str] = []
    for ds_name in model.reachable(fact):  # BFS order → from_dataset always emitted first
        rel = needed_rel_by_target.get(ds_name)
        if rel is None:
            continue
        to_source = model.datasets[rel.to_dataset].source
        on = " AND ".join(f"{rel.from_dataset}.{fc} = {rel.to_dataset}.{tc}" for fc, tc in zip(rel.from_columns, rel.to_columns))
        clauses.append(f"LEFT JOIN {to_source} AS {rel.to_dataset} ON {on}")
    return clauses


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

    Raises ``ValueError`` (naming the valid options) on any unknown or
    out-of-grain metric/dimension/filter/grain, so the agent can self-correct.
    """
    group_by = list(dict.fromkeys(group_by or []))  # de-dup, keep order
    equality_filters = dict(equality_filters or {})

    metric_def = model.metrics.get(metric)
    if metric_def is None:
        raise ValueError(f"Unknown metric '{metric}'. Available metrics: {', '.join(sorted(model.metrics)) or '(none)'}.")
    fact = metric_def.fact

    if time_grain is not None and time_grain not in ALLOWED_TIME_GRAINS:
        raise ValueError(f"Unknown time_grain '{time_grain}'. Allowed: {', '.join(ALLOWED_TIME_GRAINS)}.")
    if not isinstance(limit, int) or limit < 1 or limit > _MAX_LIMIT:
        raise ValueError(f"'limit' must be an integer between 1 and {_MAX_LIMIT}.")

    used_datasets: set[str] = {fact}
    group_dims: list[Dimension] = []
    for name in group_by:
        dim = model.resolve_dimension(fact, name)  # raises if out of grain
        group_dims.append(dim)
        used_datasets.add(dim.dataset)

    filter_dims: list[tuple[Dimension, Any]] = []
    for key, value in equality_filters.items():
        dim = model.resolve_dimension(fact, key)
        filter_dims.append((dim, value))
        used_datasets.add(dim.dataset)

    time_dim = model.time_dimension(fact) if (date_start is not None or date_end is not None) else None
    if (date_start is not None or date_end is not None) and time_dim is None:
        raise ValueError("This metric has no reachable time dimension; date filters are not supported.")
    if time_dim is not None:
        used_datasets.add(time_dim.dataset)

    params: dict[str, Any] = {}
    select_parts: list[str] = []
    group_parts: list[str] = []
    for dim in group_dims:
        alias = _safe_alias(dim.name, kind="Dimension")
        if dim.is_time and time_grain is not None:
            expr = f"date_trunc(:time_grain, {dim.expression})"
            params["time_grain"] = time_grain
        else:
            expr = dim.expression
        select_parts.append(f"{expr} AS {alias}")
        group_parts.append(expr)

    select_parts.append(f"{metric_def.expression} AS {_safe_alias(metric, kind='Metric')}")

    where_parts: list[str] = []
    for idx, (dim, value) in enumerate(filter_dims):
        param = f"flt_{idx}"
        where_parts.append(f"{dim.expression} = :{param}")
        params[param] = value
    if time_dim is not None and date_start is not None:
        where_parts.append(f"{time_dim.expression} >= CAST(:date_start AS timestamptz)")
        params["date_start"] = date_start
    if time_dim is not None and date_end is not None:
        where_parts.append(f"{time_dim.expression} <= CAST(:date_end AS timestamptz)")
        params["date_end"] = date_end

    fact_source = model.datasets[fact].source
    sql_lines = [
        f"SELECT {', '.join(select_parts)}",
        f"FROM {fact_source} AS {fact}",
        *_join_clauses(model, fact, used_datasets),
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
        fact=fact,
        group_by=tuple(group_by),
    )
