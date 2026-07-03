"""OSI semantic layer for ngv-trader.

A vendor-neutral (Open Semantic Interchange) description of trading metrics and
dimensions, plus a resolver that compiles a chosen metric + dimensions + filters
into a single read-only SQL query. This is the Postgres analog of a Snowflake
semantic view: the physical ``v_trade_realized_pnl`` view is the fact source, the
OSI YAML supplies the dimensions/metrics/synonyms, and the resolver plays the role
of ``SELECT ... FROM SEMANTIC_VIEW(...)``. The tradebot drives it by *name*, never
by writing SQL.
"""

from src.services.semantic.loader import SemanticModel, get_model, load_model
from src.services.semantic.resolver import MetricQuery, build_metric_query

__all__ = [
    "SemanticModel",
    "get_model",
    "load_model",
    "MetricQuery",
    "build_metric_query",
]
