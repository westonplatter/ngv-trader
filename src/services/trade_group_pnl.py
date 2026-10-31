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
(`realized_pnl` grouped/filtered by `trade_group`); this service is for the live overlay
figures the semantic resolver can't express.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime
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
from src.services.execution_pnl import execution_lifecycle, realized_pnl_total
from src.services.intraday_overlay import (
    OverlayTotals,
    PositionView,
    dedupe_live_realized,
    intraday_unrealized_total,
    is_live_stale,
    is_overlay_superseded,
    merge_positions,
    overlay_totals,
)


def trade_group_realized_pnl(executions: Iterable[Any]) -> float | None:
    """Realized PnL over a group's linked executions: the shared combo-aware rule.

    A group links to specific execution rows, so every linked row counts (see
    :func:`realized_pnl_total` for why a trade, by contrast, filters revisions).
    """
    return realized_pnl_total(executions)


def _combine_total(realized: float | None, settled_unrealized: float | None) -> float | None:
    """Settled Total PnL, or ``None`` when both components are absent."""
    if realized is None and settled_unrealized is None:
        return None
    return (realized or 0.0) + (settled_unrealized or 0.0)


PairKey = tuple[int, int]


def _signed_quantity(side: str | None, quantity: float) -> float:
    """Signed fill quantity: FlexQuery stores it signed, TWS unsigned with a side."""
    if side is None:
        return quantity
    return -abs(quantity) if side.upper() in {"SLD", "SELL"} else abs(quantity)


def _net_held(fills: list[tuple[float, str | None]]) -> float:
    """Quantity a group still holds from its own ``(signed_qty, lifecycle)`` fills.

    Opens (and fills with no indicator) build the holding. A tagged close only
    reduces it when it points the other way: a same-direction close unwound a
    lot the group never opened (e.g. selling out a prior long before opening a
    short), so it is not this group's exposure. Never flips past zero.
    """
    opened = sum(qty for qty, lifecycle in fills if lifecycle != "Close")
    held = opened + sum(qty for qty, lifecycle in fills if lifecycle == "Close" and qty * opened < 0)
    return held if held * opened > 0 else 0.0


@dataclass(frozen=True)
class GroupHoldings:
    """Signed quantity a trade group holds per ``(account_id, con_id)``.

    ``settled`` counts settled fills only (it apportions the FlexQuery
    snapshot); ``total`` adds the group's tagged unsettled fills (it apportions
    the live position).
    """

    settled: dict[PairKey, float]
    total: dict[PairKey, float]


def group_holdings(settled_execs: Iterable[Any], live_execs: Iterable[Any] = ()) -> GroupHoldings:
    """Per-position holdings from a group's tagged settled + unsettled fills.

    Combo summaries are skipped (their legs carry the quantity), as are
    superseded revisions. Unsettled fills carry no open/close indicator.
    """
    settled_fills: dict[PairKey, list[tuple[float, str | None]]] = {}
    for ex in settled_execs:
        if ex.con_id is None or ex.exec_role == "combo_summary" or not ex.is_canonical:
            continue
        settled_fills.setdefault((ex.account_id, ex.con_id), []).append((_signed_quantity(ex.side, ex.quantity), execution_lifecycle(ex.raw)))
    live_fills: dict[PairKey, list[tuple[float, str | None]]] = {}
    for ex in live_execs:
        if ex.con_id is None or ex.exec_role == "combo_summary":
            continue
        live_fills.setdefault((ex.account_id, ex.con_id), []).append((_signed_quantity(ex.side, ex.quantity), None))
    return GroupHoldings(
        settled={key: _net_held(fills) for key, fills in settled_fills.items()},
        total={key: _net_held(settled_fills.get(key, []) + live_fills.get(key, [])) for key in settled_fills.keys() | live_fills.keys()},
    )


def held_fraction(held: float | None, position: float | None) -> float:
    """Share of an account position a group holds, in ``[0, 1]``."""
    if held is None or not position or held * position <= 0:
        return 0.0
    return min(abs(held) / abs(position), 1.0)


def _scaled(value: float | None, share: float) -> float | None:
    return None if value is None else value * share


def apportion_to_group(views: list[PositionView], flex_rows: list[Any], holdings: GroupHoldings) -> tuple[list[PositionView], dict[PairKey, float]]:
    """Cut account-level positions down to the part a group's own fills hold.

    Two groups that each opened one lot of the same contract would otherwise
    both show (and total) the whole account position. Quantity, unrealized and
    position value scale pro rata; avg cost, marks and greeks are per-unit and
    stay as is. Views the group holds none of are dropped.

    Returns ``(views, flex_shares)``; pass ``flex_shares`` to ``overlay_totals``
    so the settled total is apportioned the same way.
    """
    flex_shares = {(row.account_id, row.con_id): held_fraction(holdings.settled.get((row.account_id, row.con_id)), row.position) for row in flex_rows}
    apportioned: list[PositionView] = []
    for view in views:
        key = (view.account_id, view.con_id)
        settled_share = flex_shares.get(key, 0.0)
        # A "settled" view shows snapshot numbers, so the settled share sizes it.
        position_share = held_fraction(holdings.total.get(key), view.position) if view.source == "live" else settled_share
        if position_share == 0.0:
            continue
        apportioned.append(
            replace(
                view,
                position=view.position * position_share,
                live_unrealized=_scaled(view.live_unrealized, position_share),
                settled_unrealized=_scaled(view.settled_unrealized, settled_share),
                settled_position_value=_scaled(view.settled_position_value, settled_share),
            )
        )
    return apportioned, flex_shares


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
    # Newest settled ``Position.as_of_date`` per account. The watermark that says
    # which live captures are still current — needed by ``merge_positions`` as
    # well as by the row filter below, so it travels with the rows it qualifies.
    account_as_of: dict[int, date]

    @classmethod
    def empty(cls) -> OverlayContext:
        return cls(flex_rows=[], live_rows=[], quotes={}, live_execs=[], magnifiers={}, metrics={}, expiries={}, account_as_of={})


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
        account_as_of=account_as_of,
    )


# ---------------------------------------------------------------------------
# The facade: a group's ledger in, its overlay out.
#
# Every consumer of the live-over-settled overlay — the detail endpoint, the
# batched list behind the Strategy P&L table, and the single-group service the
# tradebot and MCP tools call — runs the same pipeline on the same inputs:
# load_overlay_context → merge_positions → apportion_to_group → overlay_totals.
# It lives here once. Callers choose only how the ledgers are loaded.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupLedger:
    """What one trade group has been assigned: its settled fills and the tagged
    unsettled fills that have not settled yet. Everything the overlay needs about
    the group — its position scope, holdings, and realized PnL — derives from these.

    ``extra_pairs`` are positions whose only link to the group is a live
    assignment whose fill row is absent (the link table carries the pair);
    :func:`load_group_ledgers` fills it in.
    """

    executions: list[Any]
    live_fills: list[Any] = field(default_factory=list)
    extra_pairs: frozenset[PairKey] = frozenset()

    @property
    def pairs(self) -> set[PairKey]:
        """``(account_id, con_id)`` pairs the group's positions are drawn from."""
        pairs = {(ex.account_id, ex.con_id) for ex in self.executions if ex.con_id is not None}
        pairs |= {(ex.account_id, ex.con_id) for ex in self.live_fills if ex.con_id is not None}
        return pairs | set(self.extra_pairs)

    @property
    def settled_exec_ids(self) -> set[str]:
        return {ex.ib_exec_id for ex in self.executions if ex.ib_exec_id}

    @property
    def holdings(self) -> GroupHoldings:
        return group_holdings(self.executions, self.live_fills)

    @property
    def realized_pnl(self) -> float | None:
        return trade_group_realized_pnl(self.executions)

    def realized_pnl_by_account(self) -> dict[int, float | None]:
        """The same rule per account partition, so the parts reconcile to the total."""
        by_account: dict[int, list[Any]] = {}
        for ex in self.executions:
            by_account.setdefault(ex.account_id, []).append(ex)
        return {account_id: trade_group_realized_pnl(rows) for account_id, rows in by_account.items()}


def load_group_ledgers(
    session: Session,
    group_ids: list[int],
    *,
    account_id: int | None = None,
    include_live: bool = True,
) -> dict[int, GroupLedger]:
    """Every group's ledger in three queries (one with ``include_live=False``),
    however many groups are asked for.

    ``account_id`` narrows each ledger to that account's fills. Group membership
    is cross-account by design, so without it an account-filtered view would
    list the right groups but total every account's legs into each row.

    ``include_live=False`` skips the tagged unsettled fills; the settled-only
    figures do not need them.
    """
    stmt = (
        select(TradeGroupExecution.trade_group_id, TradeExecution)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .where(TradeGroupExecution.trade_group_id.in_(group_ids))
    )
    if account_id is not None:
        stmt = stmt.where(TradeExecution.account_id == account_id)
    execs_by_group: dict[int, list[Any]] = {}
    for group_id, execution in session.execute(stmt).all():
        execs_by_group.setdefault(group_id, []).append(execution)

    live_pairs = _tagged_live_pairs(session, group_ids, account_id) if include_live else {}
    live_fills = _tagged_live_fills(session, group_ids, account_id) if include_live else {}
    return {
        group_id: GroupLedger(
            executions=execs_by_group.get(group_id, []),
            live_fills=live_fills.get(group_id, []),
            extra_pairs=frozenset(live_pairs.get(group_id, set())),
        )
        for group_id in group_ids
    }


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


def _tagged_live_fills(session: Session, group_ids: list[int], account_id: int | None = None) -> dict[int, list[Any]]:
    """Each group's tagged unsettled ``LiveExecution`` fills, for :func:`group_holdings`."""
    stmt = (
        select(TradeGroupLiveExecution.trade_group_id, LiveExecution)
        .join(LiveExecution, LiveExecution.ib_exec_id == TradeGroupLiveExecution.ib_exec_id)
        .where(
            TradeGroupLiveExecution.trade_group_id.in_(group_ids),
            LiveExecution.ib_exec_id.not_in(select(TradeExecution.ib_exec_id)),
        )
    )
    if account_id is not None:
        stmt = stmt.where(LiveExecution.account_id == account_id)
    fills: dict[int, list[Any]] = {}
    for group_id, live_exec in session.execute(stmt).all():
        fills.setdefault(group_id, []).append(live_exec)
    return fills


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


def _combine_intraday(unrealized: float | None, realized: float | None) -> float | None:
    if unrealized is None and realized is None:
        return None
    return (unrealized or 0.0) + (realized or 0.0)


@dataclass(frozen=True)
class AccountOverlay:
    """One account's slice of a group's overlay figures."""

    unrealized: float | None  # settled
    intraday_unrealized: float | None
    intraday_realized: float | None
    intraday_total: float | None


@dataclass(frozen=True)
class GroupOverlay:
    """The live-over-settled overlay for one group: the position views cut down
    to the group's share, the group totals, and the per-account breakdown that
    reconciles to them. The rows the views were merged from ride along so a
    display layer can label them without re-querying.
    """

    views: list[PositionView]
    flex_rows: list[Any]
    live_rows: list[Any]
    expiries: dict[int, str]
    realized_pnl: float | None
    totals: OverlayTotals
    by_account: dict[int, AccountOverlay]
    # True only when the group has live-sourced marks and *every* one of them is
    # stale. A group with a mix of fresh and stale legs is not flagged: its
    # ``marks_as_of`` (the newest mark) already says how current the figures are,
    # and flagging a whole row on one stale leg trains the operator to ignore the
    # badge.
    live_is_stale: bool


def _account_breakdown(
    views: list[PositionView],
    live_execs: list[Any],
    settled_exec_ids: set[str],
    realized_by_account: dict[int, float | None],
) -> dict[int, AccountOverlay]:
    """Per-account figures using the same partitioning as the group totals."""
    views_by_account: dict[int, list[PositionView]] = {}
    for view in views:
        views_by_account.setdefault(view.account_id, []).append(view)
    live_execs_by_account: dict[int, list[Any]] = {}
    for ex in live_execs:
        live_execs_by_account.setdefault(ex.account_id, []).append(ex)

    by_account: dict[int, AccountOverlay] = {}
    for account_id in set(views_by_account) | set(realized_by_account):
        acct_views = views_by_account.get(account_id, [])
        acct_settled = [v.settled_unrealized for v in acct_views if v.settled_unrealized is not None]
        acct_unrealized = sum(acct_settled) if acct_settled else None
        acct_intraday_unrealized = intraday_unrealized_total(acct_views)
        acct_realized = realized_by_account.get(account_id)
        _, acct_live_realized = dedupe_live_realized(settled_exec_ids, live_execs_by_account.get(account_id, []))
        acct_intraday_realized = (acct_realized or 0.0) + acct_live_realized if (acct_realized is not None or acct_live_realized) else None
        by_account[account_id] = AccountOverlay(
            unrealized=acct_unrealized,
            intraday_unrealized=acct_intraday_unrealized,
            intraday_realized=acct_intraday_realized,
            intraday_total=_combine_intraday(acct_intraday_unrealized, acct_intraday_realized),
        )
    return by_account


def _overlay_one(context: OverlayContext, ledger: GroupLedger) -> GroupOverlay:
    """Run the pipeline for one group over a context loaded for its pairs (or more)."""
    pairs = ledger.pairs
    # Merge per group rather than once over a union of groups: merge_positions
    # drops a settled row when *its account* has live data, so a union-wide merge
    # would silently net-close a group whose own pairs have no live rows.
    flex_slice = [row for row in context.flex_rows if (row.account_id, row.con_id) in pairs]
    live_slice = [row for row in context.live_rows if (row.account_id, row.con_id) in pairs]
    exec_slice = [row for row in context.live_execs if (row.account_id, row.con_id) in pairs]
    views = merge_positions(flex_slice, live_slice, context.quotes, context.magnifiers, context.metrics, context.account_as_of)
    views, flex_shares = apportion_to_group(views, flex_slice, ledger.holdings)
    realized = ledger.realized_pnl
    settled_exec_ids = ledger.settled_exec_ids
    totals = overlay_totals(flex_slice, views, exec_slice, settled_exec_ids, realized, flex_shares)
    return GroupOverlay(
        views=views,
        flex_rows=flex_slice,
        live_rows=live_slice,
        expiries=context.expiries,
        realized_pnl=realized,
        totals=totals,
        by_account=_account_breakdown(views, exec_slice, settled_exec_ids, ledger.realized_pnl_by_account()),
        live_is_stale=_group_live_is_stale(views, flex_slice, live_slice),
    )


def overlay_for_ledgers(session: Session, ledgers: dict[int, GroupLedger]) -> dict[int, GroupOverlay]:
    """The overlay for every ledger, loading the rows once for all of them.

    The overlay context is loaded for the union of the ledgers' pairs (a fixed
    seven queries) and sliced per group, so the cost does not grow with the
    number of groups. A caller that already holds a group's rows builds its
    :class:`GroupLedger` directly and skips :func:`load_group_ledgers`.
    """
    all_pairs: set[PairKey] = set()
    for ledger in ledgers.values():
        all_pairs |= ledger.pairs
    context = load_overlay_context(session, all_pairs)
    return {group_id: _overlay_one(context, ledger) for group_id, ledger in ledgers.items()}


def overlay_for_groups(session: Session, group_ids: list[int], *, account_id: int | None = None) -> dict[int, GroupOverlay]:
    """Load the ledgers and compute the overlay: the whole pipeline in one call."""
    return overlay_for_ledgers(session, load_group_ledgers(session, group_ids, account_id=account_id))


@dataclass(frozen=True)
class TradeGroupBatchPnl:
    """Per-group PnL figures from the batched read path."""

    realized_pnl: float | None
    settled_unrealized_pnl: float | None
    intraday_unrealized_pnl: float | None = None
    intraday_realized_pnl: float | None = None
    intraday_total_pnl: float | None = None
    marks_as_of: datetime | None = None
    # See ``GroupOverlay.live_is_stale``.
    live_is_stale: bool = False

    @property
    def total_pnl(self) -> float | None:
        """Settled Total PnL — realized + settled unrealized, never the overlay."""
        return _combine_total(self.realized_pnl, self.settled_unrealized_pnl)


def trade_group_batch_pnls(
    session: Session,
    group_ids: list[int],
    *,
    include_intraday: bool = True,
    account_id: int | None = None,
) -> dict[int, TradeGroupBatchPnl]:
    """Realized + settled/intraday PnL for many trade groups, without an N+1.

    Query count is fixed in ``len(group_ids)``: the three the ledgers need plus
    the seven the overlay context needs. Only the per-group *slicing* is per
    group, and that is pure Python over already-loaded rows.

    ``include_intraday=False`` skips the overlay entirely and answers from two
    queries (executions + the settled Position snapshot), which is the cost the
    list endpoint's existing consumers already pay.

    Attribution matches ``GET /trade-groups/{id}/executions``: a group holds the
    part of each ``(account_id, con_id)`` position that its own tagged fills
    opened (see :func:`apportion_to_group`), so a contract split across two
    groups is counted once, not in full in both.

    ``account_id`` scopes every figure to that account's legs, matching the
    detail endpoint's per-account breakdown. Groups are cross-account, so an
    account-filtered caller must pass it or the rows will report book-wide
    totals under an account heading.
    """
    if not group_ids:
        return {}

    if not include_intraday:
        ledgers = load_group_ledgers(session, group_ids, account_id=account_id, include_live=False)
        all_pairs: set[PairKey] = set()
        for ledger in ledgers.values():
            all_pairs |= ledger.pairs
        settled_by_pair: dict[PairKey, tuple[float, float]] = {}
        if all_pairs:
            pos_rows = session.execute(
                select(Position.account_id, Position.con_id, Position.position, Position.fifo_pnl_unrealized).where(
                    sa_tuple(Position.account_id, Position.con_id).in_(list(all_pairs)),
                    Position.position != 0,
                )
            ).all()
            for account_id, con_id, position, fifo in pos_rows:
                if fifo is not None:
                    settled_by_pair[(account_id, con_id)] = (position, fifo)
        result: dict[int, TradeGroupBatchPnl] = {}
        for group_id, ledger in ledgers.items():
            held = ledger.holdings.settled
            values = [
                fifo * held_fraction(held.get(pair), position) for pair in ledger.pairs if pair in settled_by_pair for position, fifo in [settled_by_pair[pair]]
            ]
            result[group_id] = TradeGroupBatchPnl(
                realized_pnl=ledger.realized_pnl,
                settled_unrealized_pnl=sum(values) if values else None,
            )
        return result

    return {
        group_id: TradeGroupBatchPnl(
            realized_pnl=overlay.realized_pnl,
            settled_unrealized_pnl=overlay.totals.settled_unrealized,
            intraday_unrealized_pnl=overlay.totals.intraday_unrealized,
            intraday_realized_pnl=overlay.totals.intraday_realized,
            intraday_total_pnl=overlay.totals.intraday_total,
            marks_as_of=overlay.totals.marks_as_of,
            live_is_stale=overlay.live_is_stale,
        )
        for group_id, overlay in overlay_for_groups(session, group_ids, account_id=account_id).items()
    }


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

    Attribution matches the detail UI: the group holds the part of each
    ``(account_id, con_id)`` position its own tagged fills opened (see
    :func:`apportion_to_group`), so a contract split across groups is counted once.
    """
    group = session.get(TradeGroup, group_id)
    if group is None:
        raise ValueError(f"Trade group #{group_id} not found.")

    overlay = overlay_for_groups(session, [group_id])[group_id]
    return TradeGroupPnl(
        group_id=group.id,
        group_name=group.name,
        realized_pnl=overlay.realized_pnl,
        settled_unrealized_pnl=overlay.totals.settled_unrealized,
        intraday_unrealized_pnl=overlay.totals.intraday_unrealized,
        intraday_realized_pnl=overlay.totals.intraday_realized,
        intraday_total_pnl=overlay.totals.intraday_total,
        marks_as_of=overlay.totals.marks_as_of,
    )
