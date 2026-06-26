"""Execute a resolved :class:`MetricQuery` against Postgres, read-only.

Defense in depth on top of the resolver: every metric query runs in its own
``READ ONLY`` transaction with a short ``statement_timeout`` and is always rolled
back. The resolver guarantees a single parameterized ``SELECT``; this guarantees
it cannot write or run long even if that ever regressed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from src.services.semantic.resolver import MetricQuery

_STATEMENT_TIMEOUT_MS = 5000


def _jsonify(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def run_metric_query(bind: Engine | Connection, query: MetricQuery) -> list[dict[str, Any]]:
    """Run ``query`` read-only and return JSON-safe rows."""
    if isinstance(bind, Engine):
        conn = bind.connect()
        owns_conn = True
    else:
        conn = bind
        owns_conn = False

    try:
        # SET TRANSACTION READ ONLY must be the first statement in the tx; the
        # autobegin transaction starts here. SET LOCAL scopes the timeout to it.
        conn.execute(text("SET TRANSACTION READ ONLY"))
        conn.execute(text(f"SET LOCAL statement_timeout = {_STATEMENT_TIMEOUT_MS}"))
        result = conn.execute(text(query.sql), query.params)
        return [{key: _jsonify(val) for key, val in row._mapping.items()} for row in result]
    finally:
        conn.rollback()
        if owns_conn:
            conn.close()
