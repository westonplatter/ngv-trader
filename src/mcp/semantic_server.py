"""Stdio MCP server exposing the OSI semantic layer to external LLM agents.

Lets a CLI agent (e.g. Claude Code on a Mac) run business-analyst metrics by
*name* — it never writes SQL. This is the same path the in-app tradebot
``query_metric`` tool uses: the OSI model is the allow-list, the resolver compiles
a metric + dimensions + filters into one parameterized SELECT, and the executor
runs it read-only with a statement timeout.

Run it:
    uv run --extra mcp python -m src.mcp.semantic_server

Database connection (use a read-only role — see docs/design/semantic-queries.md):
    NGV_SEMANTIC_DATABASE_URL=postgresql://ngv_analyst:***@host:5432/ngtrader_prod
If unset, falls back to the app's DB_* environment variables.

The tag and task tools (docs/design/tags-and-tasks.md) write, so they do not
use that read-only connection: they call the app's local REST API, the same one
the UI uses. Every write is recorded as ``agent:<NGV_AGENT_NAME>``.
    NGV_API_URL=http://localhost:8000/api/v1   (default)
    NGV_AGENT_NAME=local-llm                   (default)
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from mcp.server import MCPServer
from src.services.semantic.executor import run_metric_query
from src.services.semantic.loader import get_model
from src.services.semantic.resolver import ALLOWED_TIME_GRAINS, build_metric_query
from src.services.trade_group_pnl import (
    compute_trade_group_pnl,
    resolve_trade_group,
    search_trade_groups,
)

mcp = MCPServer("ngv-semantic")


@lru_cache(maxsize=1)
def _get_engine() -> Engine:
    # Fail closed: require an explicit connection string so a misconfiguration
    # can't silently fall back to the app's read-write role. Point this at the
    # read-only ngv_analyst role (see docs/design/semantic-queries.md).
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


@mcp.tool()
def find_trade_groups(query: str, limit: int = 5) -> dict[str, Any]:
    """Fuzzy-find trade groups by a free-text phrase — the 'find the group' step.

    Resolve a human phrase to concrete trade group(s) BEFORE looking up PnL, when
    you don't know the exact group name. The phrase is a fuzzy predicate, not a
    symbol: every token must appear in the group name, but order and punctuation
    don't matter — "MP", "gamma delta", "dec 27", "covered call" all work.

    Prefer this over filtering a metric by symbol: `contracts.symbol` is missing
    for many option con_ids, so symbol-filtered PnL silently undercounts. The
    reliable path is phrase -> find_trade_groups -> pick a group -> its PnL.

    Args:
        query: Free-text phrase to match against trade group names.
        limit: Max candidates to return (1-25).

    Returns ranked ``matches`` [{id, name, score}]. If more than one is returned
    the phrase is ambiguous — pick one and pass its ``id`` (or exact ``name``) to
    ``trade_group_pnl`` for realized + unrealized PnL, or to ``query_metric``
    (``filters={"trade_group": name}``). Matches names only: a strategy whose name omits
    its symbol won't be found by that symbol.
    """
    text = (query or "").strip()
    if not text:
        return {"query": query, "count": 0, "matches": []}
    capped = max(1, min(int(limit), 25))
    with Session(_get_engine()) as session:
        matches = search_trade_groups(session, text, limit=capped)
    return {
        "query": text,
        "count": len(matches),
        "matches": [{"id": m.id, "name": m.name, "score": m.score} for m in matches],
        "next": "Pass a match's id or exact name to trade_group_pnl(group=...) for realized + unrealized PnL.",
    }


@mcp.tool()
def trade_group_pnl(group: str) -> dict[str, Any]:
    """Realized + unrealized PnL for ONE trade group (the detail-view figures).

    Args:
        group: Trade group numeric id, exact name, OR a fuzzy phrase. A phrase
            that matches exactly one group resolves automatically; if it matches
            several, the error lists the candidates (use find_trade_groups to
            search/disambiguate first).

    Returns realized_pnl (settled), settled_unrealized_pnl, and the live-overlay
    figures intraday_unrealized_pnl / intraday_realized_pnl / intraday_total_pnl
    with marks_as_of. Intraday figures are 'as of the last live TWS refresh' (not
    tick-live) and are a per-group attribution (not additive across groups). For
    analytics across many groups, use query_metric (e.g. realized_pnl by trade_group).
    """
    text = group.strip()
    handle: int | str = int(text) if text.lstrip("-").isdigit() else text
    with Session(_get_engine()) as session:
        resolved = resolve_trade_group(session, handle)
        return compute_trade_group_pnl(session, resolved.id).as_dict()


# ---------------------------------------------------------------------------
# Tags and tasks — thin wrappers over the local REST API
# ---------------------------------------------------------------------------


def _agent() -> str:
    return f"agent:{os.environ.get('NGV_AGENT_NAME', 'local-llm')}"


def _api(method: str, path: str, body: dict[str, Any] | None = None, params: dict[str, Any] | None = None) -> Any:
    """Call the local API; raise a readable error with the API's ``detail`` on failure."""
    base = os.environ.get("NGV_API_URL", "http://localhost:8000/api/v1").rstrip("/")
    query = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}, doseq=True)
    url = f"{base}{path}" + (f"?{query}" if query else "")
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 — fixed local API URL
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc
    return json.loads(raw) if raw else None


@mcp.tool()
def search_tags(query: str | None = None) -> list[dict[str, Any]]:
    """List free-form tags, most used first, optionally matching ``query``.

    Tags are sticky notes ("long-beta", "risk-off", "offset-risk") on trades,
    positions, trade groups, and tasks. They are not strategies or trade groups.
    Check here before creating a tag so you reuse an existing one.
    """
    return _api("GET", "/tags", params={"q": query})


@mcp.tool()
def create_tag(value: str, color: str | None = None) -> dict[str, Any]:
    """Create a tag, or return the existing one whose name matches after folding
    case, spaces, dashes, and underscores."""
    return _api("POST", "/tags", {"value": value, "color": color, "created_by": _agent()})


@mcp.tool()
def tag_items(tags: list[str | int], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach tags (names or ids; unknown names are created) to items.

    Only tag what the person asked for — there is no automatic tagging. Each item
    is a dict with ``entity_type`` and its key:
        {"entity_type": "trade", "id": <trades.id>}                  a settled order
        {"entity_type": "live_execution", "ib_exec_id": "<id>"}      an unsettled TWS fill;
                                                                     covers its whole order
        {"entity_type": "position", "account_id": <id>, "con_id": <conid>}
        {"entity_type": "trade_group", "id": <id>}
        {"entity_type": "task", "id": <id>}
    """
    return _api("POST", "/tag-links", {"tags": tags, "items": items, "created_by": _agent()})


@mcp.tool()
def untag_items(tags: list[str | int], items: list[dict[str, Any]]) -> dict[str, Any]:
    """Remove tags from items (same item shape as ``tag_items``)."""
    return _api("DELETE", "/tag-links", {"tags": tags, "items": items, "created_by": _agent()})


@mcp.tool()
def find_by_tags(
    all_tags: list[str] | None = None,
    any_tags: list[str] | None = None,
    none_tags: list[str] | None = None,
    entity_type: str | None = None,
    include_ended: bool = False,
) -> dict[str, Any]:
    """Find items by tag: every ``all_tags``, at least one ``any_tags``, no ``none_tags``.

    ``entity_type`` narrows to trade, live_execution, position, trade_group, or
    task. Tags on positions that have since closed are left out unless
    ``include_ended``. Returns labels and tags only — no P&L.
    """
    return _api(
        "GET",
        "/tags/search",
        params={"all": all_tags, "any": any_tags, "none": none_tags, "entity_type": entity_type, "include_ended": str(include_ended).lower()},
    )


@mcp.tool()
def list_tasks(  # noqa: PLR0913 — mirrors the endpoint's filters
    status: str | None = None,
    include_done: bool = False,
    tag: str | None = None,
    strategy_id: int | None = None,
    trade_group_id: int | None = None,
    symbol: str | None = None,
) -> list[dict[str, Any]]:
    """List tasks, newest first, with their links and tags. Done tasks are hidden
    unless ``include_done`` or ``status="done"``. Status is todo, in_progress, or done."""
    return _api(
        "GET",
        "/tasks",
        params={
            "status": status,
            "include_done": str(include_done).lower(),
            "tag": tag,
            "strategy_id": strategy_id,
            "trade_group_id": trade_group_id,
            "symbol": symbol,
        },
    )


@mcp.tool()
def create_task(
    title: str,
    notes: str | None = None,
    status: str = "todo",
    links: list[dict[str, Any]] | None = None,
    tags: list[str | int] | None = None,
) -> dict[str, Any]:
    """Create a task, optionally linked to items and tagged.

    ``links`` use the ``tag_items`` item shape, except a task links to a
    ``{"entity_type": "strategy", "id": <id>}`` instead of another task.
    """
    return _api(
        "POST",
        "/tasks",
        {"title": title, "notes": notes, "status": status, "links": links or [], "tags": tags or [], "created_by": _agent()},
    )


@mcp.tool()
def update_task(task_id: int, title: str | None = None, notes: str | None = None, status: str | None = None) -> dict[str, Any]:
    """Change a task's title, notes, or status (todo, in_progress, done)."""
    body: dict[str, Any] = {key: value for key, value in {"title": title, "notes": notes, "status": status}.items() if value is not None}
    return _api("PATCH", f"/tasks/{task_id}", body)


@mcp.tool()
def delete_task(task_id: int) -> dict[str, Any]:
    """Delete a task and its links. Prefer marking it done unless asked to delete."""
    _api("DELETE", f"/tasks/{task_id}")
    return {"deleted": task_id}


@mcp.tool()
def link_task(task_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Link items to a task (item shape as in ``create_task``)."""
    return _api("POST", f"/tasks/{task_id}/links", {"items": items, "created_by": _agent()})


@mcp.tool()
def unlink_task(task_id: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Unlink items from a task (item shape as in ``create_task``)."""
    return _api("DELETE", f"/tasks/{task_id}/links", {"items": items, "created_by": _agent()})


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
