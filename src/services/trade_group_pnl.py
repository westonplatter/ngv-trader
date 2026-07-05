"""Trade-group PnL: realized + settled/intraday unrealized for one group.

Single source for the numbers shown in the trade group detail UI. The API
endpoint (`GET /trade-groups/{id}/executions`) and the tradebot/MCP
`trade_group_pnl` tool both go through here, so the figures cannot diverge.

Why a service (not a SQL semantic metric): intraday unrealized/total are a
read-time merge of live TWS state (`live_positions` + `latest_quote` +
`live_executions`) over the settled FlexQuery snapshot, with precedence and a
multiplier-inclusive cost-basis convention that lives in `intraday_overlay.py`
(and is still pending live validation). Reproducing that in SQL would fork an
unvalidated formula; instead we reuse the one Python implementation.

Realized PnL by group is *also* available as a pure SQL semantic metric
(`realized_pnl` grouped/filtered by `tag`); this service is for the live overlay
figures the semantic resolver can't express.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import tuple_ as sa_tuple
from sqlalchemy.orm import Session

from src.models import (
    LatestQuote,
    LiveExecution,
    LivePosition,
    Position,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
)
from src.services.execution_pnl import execution_realized_pnl as _execution_realized_pnl
from src.services.intraday_overlay import merge_positions, overlay_totals


def trade_group_realized_pnl(executions: list[Any]) -> float | None:
    """Combo-aware realized PnL over a group's assigned executions.

    Mirrors the trade-group detail rule: when ``combo_summary`` rows are present
    they carry the spread's rolled-up realized PnL (sum those plus any
    standalone, non-leg rows); otherwise sum every non-combo_summary fill.
    """
    combo_totals = [r for ex in executions if ex.exec_role == "combo_summary" for r in [_execution_realized_pnl(ex.raw)] if r is not None]
    if combo_totals:
        standalone = [r for ex in executions if ex.exec_role not in {"combo_summary", "leg"} for r in [_execution_realized_pnl(ex.raw)] if r is not None]
        return sum(combo_totals) + sum(standalone)

    values = [r for ex in executions if ex.exec_role != "combo_summary" for r in [_execution_realized_pnl(ex.raw)] if r is not None]
    return sum(values) if values else None


def load_overlay_inputs(
    session: Session,
    account_con_pairs: set[tuple[int, int]],
) -> tuple[list[Any], list[Any], dict[int, Any], list[Any]]:
    """Load the settled + live rows the overlay merge needs for a set of pairs.

    Returns ``(flex_rows, live_rows, quotes_by_con_id, live_execs)``.
    """
    pairs = list(account_con_pairs)
    if not pairs:
        return [], [], {}, []

    flex_rows = list(
        session.execute(
            select(Position)
            .where(sa_tuple(Position.account_id, Position.con_id).in_(pairs), Position.position != 0)
            .order_by(Position.account_id.asc(), Position.con_id.asc())
        )
        .scalars()
        .all()
    )
    live_rows = list(
        session.execute(select(LivePosition).where(sa_tuple(LivePosition.account_id, LivePosition.con_id).in_(pairs), LivePosition.position != 0))
        .scalars()
        .all()
    )
    con_ids = {p.con_id for p in flex_rows} | {p.con_id for p in live_rows}
    quotes: dict[int, Any] = {}
    if con_ids:
        quotes = {q.con_id: q for q in session.execute(select(LatestQuote).where(LatestQuote.con_id.in_(list(con_ids)))).scalars().all()}
    live_execs = list(session.execute(select(LiveExecution).where(sa_tuple(LiveExecution.account_id, LiveExecution.con_id).in_(pairs))).scalars().all())
    return flex_rows, live_rows, quotes, live_execs


@dataclass(frozen=True)
class TradeGroupPnl:
    group_id: int
    group_name: str
    realized_pnl: float | None
    settled_unrealized_pnl: float | None
    intraday_unrealized_pnl: float | None
    intraday_realized_pnl: float | None
    intraday_total_pnl: float | None
    marks_as_of: datetime | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "realized_pnl": self.realized_pnl,
            "settled_unrealized_pnl": self.settled_unrealized_pnl,
            "intraday_unrealized_pnl": self.intraday_unrealized_pnl,
            "intraday_realized_pnl": self.intraday_realized_pnl,
            "intraday_total_pnl": self.intraday_total_pnl,
            "marks_as_of": self.marks_as_of.isoformat() if self.marks_as_of else None,
        }


@dataclass(frozen=True)
class TradeGroupMatch:
    """A fuzzy trade-group search hit. Higher ``score`` = better match."""

    id: int
    name: str
    score: int


_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


def _search_tokens(query: str) -> list[str]:
    """Lowercase, split on any non-alphanumeric run (whitespace, ``'`` ``-`` ``+`` …)."""
    return [tok for tok in _TOKEN_SPLIT_RE.split(query.lower()) if tok]


def search_trade_groups(session: Session, query: str, limit: int = 5) -> list[TradeGroupMatch]:
    """Fuzzy-resolve a free-text phrase to trade groups by name (token-AND ILIKE).

    Every token in ``query`` must appear somewhere in the group name, but order
    and punctuation don't matter — so ``"gamma delta"``, ``"cl dec 27"`` and
    ``"dec'27"`` all find ``"CL Short Gamma + Long Delta --- Dec'27"``. Results
    are ranked best-first (exact name > full-phrase substring > more tokens >
    shorter name). An ambiguous phrase legitimately returns several candidates so
    the caller disambiguates instead of silently picking one.

    Equality-only ``query_metric`` can't express this; it's a resolution step, not
    aggregation. Matches names only — a strategy whose name omits its symbol won't
    be found by that symbol.
    """
    tokens = _search_tokens(query)
    if not tokens:
        return []
    stmt = select(TradeGroup)
    for tok in tokens:
        stmt = stmt.where(TradeGroup.name.ilike(f"%{tok}%"))
    groups = session.execute(stmt).scalars().all()

    needle = query.strip().lower()
    matches: list[TradeGroupMatch] = []
    for group in groups:
        name_lower = group.name.lower()
        score = 10 * len(tokens)  # all tokens matched (WHERE guarantees it)
        if name_lower == needle:
            score += 1000  # exact name
        elif needle in name_lower:
            score += 100  # whole phrase is a contiguous substring
        matches.append(TradeGroupMatch(id=group.id, name=group.name, score=score))
    # Tie-break on the shorter (more specific) name, then alphabetically.
    matches.sort(key=lambda m: (-m.score, len(m.name), m.name))
    return matches[:limit]


def resolve_trade_group(session: Session, group: int | str) -> TradeGroup:
    """Resolve a trade group by id, exact (case-insensitive) name, or fuzzy phrase.

    Exact matches win. If the name isn't found verbatim, fall back to
    :func:`search_trade_groups`: a single fuzzy hit resolves; multiple hits raise
    with the candidate list so the caller can pick (never silently guesses).
    """
    if isinstance(group, int):
        found = session.get(TradeGroup, group)
        if found is None:
            raise ValueError(f"Trade group #{group} not found.")
        return found
    name = str(group).strip()
    if not name:
        raise ValueError("Provide a trade group id or name.")
    exact = session.execute(select(TradeGroup).where(func.lower(TradeGroup.name) == name.lower())).scalars().all()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ValueError(f"Multiple trade groups named '{group}'; use the numeric id instead.")

    fuzzy = search_trade_groups(session, name, limit=5)
    if not fuzzy:
        raise ValueError(f"No trade group matching '{group}'. Try find_trade_groups to search by phrase.")
    if len(fuzzy) == 1:
        return session.get(TradeGroup, fuzzy[0].id)
    candidates = ", ".join(f"#{m.id} {m.name!r}" for m in fuzzy)
    raise ValueError(f"'{group}' matches multiple trade groups: {candidates}. Re-run with the exact name or numeric id.")


def compute_trade_group_pnl(session: Session, group_id: int) -> TradeGroupPnl:
    """Compute realized + settled/intraday PnL for one trade group.

    Attribution matches the detail UI: a position is attributed to the group when
    any of the group's executions touched its ``(account_id, con_id)``. This is a
    per-group figure and is NOT additive across groups (a position shared by two
    groups is counted in both).
    """
    group = session.get(TradeGroup, group_id)
    if group is None:
        raise ValueError(f"Trade group #{group_id} not found.")

    executions = list(
        session.execute(
            select(TradeExecution)
            .join(TradeGroupExecution, TradeGroupExecution.trade_execution_id == TradeExecution.id)
            .where(TradeGroupExecution.trade_group_id == group_id)
        )
        .scalars()
        .all()
    )

    realized = trade_group_realized_pnl(executions)
    account_con_pairs = {(ex.account_id, ex.con_id) for ex in executions if ex.con_id is not None}
    settled_exec_ids = {ex.ib_exec_id for ex in executions if ex.ib_exec_id}

    flex_rows, live_rows, quotes, live_execs = load_overlay_inputs(session, account_con_pairs)
    views = merge_positions(flex_rows, live_rows, quotes)
    totals = overlay_totals(flex_rows, views, live_execs, settled_exec_ids, realized)

    return TradeGroupPnl(
        group_id=group.id,
        group_name=group.name,
        realized_pnl=realized,
        settled_unrealized_pnl=totals.settled_unrealized,
        intraday_unrealized_pnl=totals.intraday_unrealized,
        intraday_realized_pnl=totals.intraday_realized,
        intraday_total_pnl=totals.intraday_total,
        marks_as_of=totals.marks_as_of,
    )
