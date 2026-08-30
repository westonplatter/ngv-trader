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
    ContractRef,
    LatestOptionMetrics,
    LatestQuote,
    LiveExecution,
    LivePosition,
    Position,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
    TradeGroupLiveExecution,
)
from src.services.execution_pnl import execution_realized_pnl as _execution_realized_pnl
from src.services.intraday_overlay import (
    is_live_stale,
    is_overlay_superseded,
    merge_positions,
    overlay_totals,
)


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


def _combine_total(realized: float | None, settled_unrealized: float | None) -> float | None:
    """Settled Total PnL, or ``None`` when both components are absent."""
    if realized is None and settled_unrealized is None:
        return None
    return (realized or 0.0) + (settled_unrealized or 0.0)


@dataclass(frozen=True)
class OverlayContext:
    """Every row the overlay merge needs for a set of ``(account_id, con_id)`` pairs.

    One loader for every consumer of the overlay: the trade-group detail
    endpoint, the single-group service, and the batched list path all merge from
    this. ``magnifiers`` in particular used to be fetched by the detail endpoint
    only, which is exactly how a cents-quoted future comes out 100x wrong on one
    screen and right on another.
    """

    flex_rows: list[Any]
    live_rows: list[Any]
    quotes: dict[int, Any]
    live_execs: list[Any]
    magnifiers: dict[int, Any]
    metrics: dict[int, Any]
    # Security-master expiry, so a position opened intraday (no settled snapshot)
    # still renders its expiry/DTE instead of collapsing onto same-strike siblings.
    expiries: dict[int, str]

    @classmethod
    def empty(cls) -> OverlayContext:
        return cls(flex_rows=[], live_rows=[], quotes={}, live_execs=[], magnifiers={}, metrics={}, expiries={})


def load_overlay_context(session: Session, account_con_pairs: set[tuple[int, int]]) -> OverlayContext:
    """Load the settled + live rows the overlay merge needs, in a fixed 7 queries.

    Query count does not depend on how many groups the pairs came from, which is
    what makes :func:`trade_group_batch_pnls` possible without an N+1.
    """
    pairs = list(account_con_pairs)
    if not pairs:
        return OverlayContext.empty()

    flex_rows = list(
        session.execute(
            select(Position)
            .where(sa_tuple(Position.account_id, Position.con_id).in_(pairs), Position.position != 0)
            .order_by(Position.account_id.asc(), Position.con_id.asc())
        )
        .scalars()
        .all()
    )
    # Newest settled snapshot per account, over the whole account rather than the
    # requested pairs — a superseded live row's own contract is by definition
    # absent from the snapshot, so a pair-scoped max would miss it.
    account_as_of = dict(
        session.execute(
            select(Position.account_id, func.max(Position.as_of_date))
            .where(Position.account_id.in_({account_id for account_id, _ in pairs}))
            .group_by(Position.account_id)
        ).all()
    )
    # Only live rows with NO settled counterpart are candidates for dropping.
    # A row that has both is already handled by the per-row is_live_stale flag,
    # which the display layer honours — dropping it here would silently remove a
    # held position instead of marking its overlay stale.
    settled_keys = {(row.account_id, row.con_id) for row in flex_rows}
    live_rows = [
        row
        for row in session.execute(select(LivePosition).where(sa_tuple(LivePosition.account_id, LivePosition.con_id).in_(pairs), LivePosition.position != 0))
        .scalars()
        .all()
        # Same blind spot the positions router had: a position closed since the
        # last TWS capture keeps an overlay row with no settled row behind it,
        # and nothing here would drop it.
        if (row.account_id, row.con_id) in settled_keys or not is_overlay_superseded(row.fetched_at, account_as_of.get(row.account_id))
    ]
    con_ids = {p.con_id for p in flex_rows} | {p.con_id for p in live_rows}
    quotes: dict[int, Any] = {}
    magnifiers: dict[int, Any] = {}
    metrics: dict[int, Any] = {}
    expiries: dict[int, str] = {}
    if con_ids:
        con_id_list = list(con_ids)
        quotes = {q.con_id: q for q in session.execute(select(LatestQuote).where(LatestQuote.con_id.in_(con_id_list))).scalars().all()}
        refs = session.execute(
            select(ContractRef.con_id, ContractRef.price_magnifier, ContractRef.contract_expiry).where(ContractRef.con_id.in_(con_id_list))
        ).all()
        magnifiers = {con_id: magnifier for con_id, magnifier, _ in refs}
        expiries = {con_id: expiry for con_id, _, expiry in refs if expiry}
        metrics = {m.con_id: m for m in session.execute(select(LatestOptionMetrics).where(LatestOptionMetrics.con_id.in_(con_id_list))).scalars().all()}
    live_execs = list(session.execute(select(LiveExecution).where(sa_tuple(LiveExecution.account_id, LiveExecution.con_id).in_(pairs))).scalars().all())
    return OverlayContext(
        flex_rows=flex_rows,
        live_rows=live_rows,
        quotes=quotes,
        live_execs=live_execs,
        magnifiers=magnifiers,
        metrics=metrics,
        expiries=expiries,
    )


@dataclass(frozen=True)
class TradeGroupBatchPnl:
    """Per-group PnL figures from the batched read path."""

    realized_pnl: float | None
    settled_unrealized_pnl: float | None
    intraday_unrealized_pnl: float | None = None
    intraday_realized_pnl: float | None = None
    intraday_total_pnl: float | None = None
    marks_as_of: datetime | None = None
    # True only when the group has live-sourced marks and *every* one of them is
    # stale. A group with a mix of fresh and stale legs is not flagged: its
    # ``marks_as_of`` (the newest mark) already says how current the figures are,
    # and flagging a whole row on one stale leg trains the operator to ignore the
    # badge.
    live_is_stale: bool = False

    @property
    def total_pnl(self) -> float | None:
        """Settled Total PnL — realized + settled unrealized, never the overlay."""
        return _combine_total(self.realized_pnl, self.settled_unrealized_pnl)


def _group_execution_index(
    session: Session,
    group_ids: list[int],
    account_id: int | None = None,
) -> tuple[dict[int, list[Any]], dict[int, set[tuple[int, int]]], dict[int, set[str]], set[tuple[int, int]]]:
    """One query for every settled execution across ``group_ids``, indexed by group.

    ``account_id`` narrows to that account's fills. Group membership is
    cross-account by design, so a group can hold legs in several accounts;
    without this, an account-filtered view would list the right groups but total
    every account's legs into each row.
    """
    stmt = (
        select(TradeGroupExecution.trade_group_id, TradeExecution)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .where(TradeGroupExecution.trade_group_id.in_(group_ids))
    )
    if account_id is not None:
        stmt = stmt.where(TradeExecution.account_id == account_id)
    exec_rows = session.execute(stmt).all()

    execs_by_group: dict[int, list[Any]] = {}
    pairs_by_group: dict[int, set[tuple[int, int]]] = {}
    settled_ids_by_group: dict[int, set[str]] = {}
    all_pairs: set[tuple[int, int]] = set()
    for group_id, execution in exec_rows:
        execs_by_group.setdefault(group_id, []).append(execution)
        if execution.con_id is not None:
            pair = (execution.account_id, execution.con_id)
            pairs_by_group.setdefault(group_id, set()).add(pair)
            all_pairs.add(pair)
        if execution.ib_exec_id:
            settled_ids_by_group.setdefault(group_id, set()).add(execution.ib_exec_id)
    return execs_by_group, pairs_by_group, settled_ids_by_group, all_pairs


def _tagged_live_pairs(session: Session, group_ids: list[int], account_id: int | None = None) -> dict[int, set[tuple[int, int]]]:
    """``(account_id, con_id)`` pairs whose only link to a group is an unsettled fill.

    Mirrors ``GET /trade-groups/{id}/executions``: a strike opened today and
    preemptively tagged is a real open position for that group, so it has to be
    in the overlay scope or a freshly-opened leg is invisible until it settles.
    """
    stmt = select(TradeGroupLiveExecution.trade_group_id, TradeGroupLiveExecution.account_id, TradeGroupLiveExecution.con_id).where(
        TradeGroupLiveExecution.trade_group_id.in_(group_ids),
        TradeGroupLiveExecution.con_id.is_not(None),
        TradeGroupLiveExecution.ib_exec_id.not_in(select(TradeExecution.ib_exec_id)),
    )
    if account_id is not None:
        stmt = stmt.where(TradeGroupLiveExecution.account_id == account_id)
    rows = session.execute(stmt).all()
    pairs: dict[int, set[tuple[int, int]]] = {}
    for group_id, account_id, con_id in rows:
        pairs.setdefault(group_id, set()).add((account_id, con_id))
    return pairs


def trade_group_account_con_pairs(session: Session, group_id: int) -> set[tuple[int, int]]:
    """The ``(account_id, con_id)`` pairs a single group's positions are drawn from."""
    _, pairs_by_group, _, _ = _group_execution_index(session, [group_id])
    pairs = set(pairs_by_group.get(group_id, set()))
    pairs |= _tagged_live_pairs(session, [group_id]).get(group_id, set())
    return pairs


def _group_live_is_stale(views: list[Any], flex_rows: list[Any], live_rows: list[Any]) -> bool:
    """True when the group has overlay-backed rows and every one of them is stale.

    Keyed on whether a live row *exists* for the view, not on the view's
    resulting ``source``. A stale overlay now resolves to ``source="settled"``
    (the snapshot supplies the numbers), so filtering on ``source == "live"``
    would find nothing and report a fully-stale group as fresh.
    """
    flex_fetched = {(p.account_id, p.con_id): p.fetched_at for p in flex_rows}
    live_fetched = {(p.account_id, p.con_id): p.fetched_at for p in live_rows}
    flags = [is_live_stale(live_fetched.get(key), flex_fetched.get(key)) for view in views for key in [(view.account_id, view.con_id)] if key in live_fetched]
    return bool(flags) and all(flags)


def trade_group_batch_pnls(
    session: Session,
    group_ids: list[int],
    *,
    include_intraday: bool = True,
    account_id: int | None = None,
) -> dict[int, TradeGroupBatchPnl]:
    """Realized + settled/intraday PnL for many trade groups, without an N+1.

    Query count is fixed in ``len(group_ids)``: one for the groups' executions,
    one for the preemptively-tagged unsettled fills, and the six the overlay
    context needs. Only the per-group *slicing* is per group, and that is pure
    Python over already-loaded rows.

    ``include_intraday=False`` skips the overlay entirely and answers from two
    queries (executions + the settled Position snapshot), which is the cost the
    list endpoint's existing consumers already pay.

    Attribution matches ``GET /trade-groups/{id}/executions``: a position belongs
    to a group when any of that group's executions touched its
    ``(account_id, con_id)``. It is a per-group figure and is **not** additive
    across groups — a position shared by two groups is counted in full in both.

    ``account_id`` scopes every figure to that account's legs, matching the
    detail endpoint's per-account breakdown. Groups are cross-account, so an
    account-filtered caller must pass it or the rows will report book-wide
    totals under an account heading.
    """
    if not group_ids:
        return {}

    execs_by_group, pairs_by_group, settled_ids_by_group, all_pairs = _group_execution_index(session, group_ids, account_id)
    realized_by_group = {group_id: trade_group_realized_pnl(execs_by_group.get(group_id, [])) for group_id in group_ids}

    if not include_intraday:
        settled_by_pair: dict[tuple[int, int], float] = {}
        if all_pairs:
            pos_rows = session.execute(
                select(Position.account_id, Position.con_id, Position.fifo_pnl_unrealized).where(
                    sa_tuple(Position.account_id, Position.con_id).in_(list(all_pairs)),
                    Position.position != 0,
                )
            ).all()
            for account_id, con_id, fifo in pos_rows:
                if fifo is not None:
                    settled_by_pair[(account_id, con_id)] = fifo
        result: dict[int, TradeGroupBatchPnl] = {}
        for group_id in group_ids:
            values = [settled_by_pair[pair] for pair in pairs_by_group.get(group_id, set()) if pair in settled_by_pair]
            result[group_id] = TradeGroupBatchPnl(
                realized_pnl=realized_by_group[group_id],
                settled_unrealized_pnl=sum(values) if values else None,
            )
        return result

    for group_id, extra in _tagged_live_pairs(session, group_ids, account_id).items():
        pairs_by_group.setdefault(group_id, set()).update(extra)
        all_pairs |= extra

    context = load_overlay_context(session, all_pairs)

    result = {}
    for group_id in group_ids:
        pairs = pairs_by_group.get(group_id, set())
        # Merge per group rather than once over the union: merge_positions drops
        # a settled row when *its account* has live data, so a union-wide merge
        # would silently net-close a group whose own pairs have no live rows.
        # Slicing first keeps the batch identical to the single-group path (R6);
        # the queries above already ran once, so this costs no round-trips.
        flex_slice = [row for row in context.flex_rows if (row.account_id, row.con_id) in pairs]
        live_slice = [row for row in context.live_rows if (row.account_id, row.con_id) in pairs]
        exec_slice = [row for row in context.live_execs if (row.account_id, row.con_id) in pairs]
        views = merge_positions(flex_slice, live_slice, context.quotes, context.magnifiers, context.metrics)
        totals = overlay_totals(
            flex_slice,
            views,
            exec_slice,
            settled_ids_by_group.get(group_id, set()),
            realized_by_group[group_id],
        )
        result[group_id] = TradeGroupBatchPnl(
            realized_pnl=realized_by_group[group_id],
            settled_unrealized_pnl=totals.settled_unrealized,
            intraday_unrealized_pnl=totals.intraday_unrealized,
            intraday_realized_pnl=totals.intraday_realized,
            intraday_total_pnl=totals.intraday_total,
            marks_as_of=totals.marks_as_of,
            live_is_stale=_group_live_is_stale(views, flex_slice, live_slice),
        )
    return result


def trade_group_total_pnls(session: Session, group_ids: list[int], account_id: int | None = None) -> dict[int, float | None]:
    """Batched settled Total PnL (realized + settled unrealized) per trade group.

    Returns ``{group_id: total_pnl}`` matching the trade-group detail panel's
    "Total PnL" headline using the *settled* figures (the FlexQuery snapshot),
    NOT the intraday/live overlay. ``None`` when a group has neither realized nor
    settled-unrealized data.

    A thin projection of :func:`trade_group_batch_pnls` so the settled total and
    the split figures can never drift apart; still two queries regardless of
    ``len(group_ids)``.
    """
    return {group_id: row.total_pnl for group_id, row in trade_group_batch_pnls(session, group_ids, include_intraday=False, account_id=account_id).items()}


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
    # Preemptively-tagged unsettled fills open positions too — include them so
    # this service and the detail endpoint scope the overlay identically.
    account_con_pairs |= _tagged_live_pairs(session, [group_id]).get(group_id, set())
    settled_exec_ids = {ex.ib_exec_id for ex in executions if ex.ib_exec_id}

    context = load_overlay_context(session, account_con_pairs)
    views = merge_positions(context.flex_rows, context.live_rows, context.quotes, context.magnifiers, context.metrics)
    totals = overlay_totals(context.flex_rows, views, context.live_execs, settled_exec_ids, realized)

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
