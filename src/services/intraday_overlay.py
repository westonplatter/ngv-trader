"""Read-time merge of the live TWS overlay onto the FlexQuery snapshot.

Pure functions over already-loaded rows — no DB or HTTP. The TradeGroup
executions endpoint (and, optionally, the portfolio Positions endpoint) load
the FlexQuery snapshot, ``live_positions``, ``latest_quote``, and
``live_executions`` rows, then call these helpers to compose the unified view.

Cost-basis / multiplier convention (best-guess, pending live TWS validation)
---------------------------------------------------------------------------
IBKR ``ib.positions()`` reports ``avgCost`` as the **per-unit cost that already
includes the contract multiplier** (i.e. for a future/option ``avgCost`` is the
full dollar cost of one contract, ~ entry_price × multiplier; for a stock the
multiplier is 1 so ``avgCost`` is per-share). Therefore:

    cost_basis   = qty * avg_cost                  # avg_cost is multiplier-inclusive
    market_value = qty * mark * multiplier         # mark is a per-unit price
    unrealized   = market_value - cost_basis
                 = qty * mark * multiplier - qty * avg_cost

``multiplier`` is the contract multiplier (e.g. "100" for equity options, "1"/
absent for stocks). This convention is encoded once here and reused everywhere.
TODO(live-validation): confirm against one known FUT, STK, and OPT position vs
the TWS UI during market hours; adjust here if avgCost semantics differ.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

# Reference timezone for the "prior calendar day" live-staleness boundary.
# Mountain Time via zoneinfo so DST transitions are handled correctly (no
# hardcoded UTC offset).
_MT_ZONE = ZoneInfo("America/Denver")

# Reference timezone for the overlay-supersede watermark. Chicago because it is
# the southern/western bound of the venues traded here: no exchange's trade date
# runs more than one day ahead of the CT calendar date (CME rolls 17:00 CT, Blue
# Ocean ATS runs 20:00-04:00 ET, ASX/Tokyo sit one day forward). That +1-day
# bound is what makes the strict ">" comparison in is_overlay_superseded safe
# for every instrument without a per-venue session calendar.
_CT_ZONE = ZoneInfo("America/Chicago")

# Instruments that trade nearly continuously, where an hours-old mark during an
# open session is genuinely stale rather than a valid close.
_CONTINUOUS_SEC_TYPES = frozenset({"FUT", "FOP"})

# How old a continuously-traded instrument's mark may be before it stops
# presenting as live. Equity and equity-option marks are not age-capped: their
# last print is the close and stays valid until the next session.
CONTINUOUS_MARK_MAX_AGE = timedelta(hours=1)


def _midnight_mt(moment: datetime) -> datetime:
    """Most recent America/Denver midnight at or before ``moment``, tz-aware.

    Converts ``moment`` into Mountain Time and floors to 00:00 of that MT
    calendar day. The result stays tz-aware (in MT), so comparing it against
    other tz-aware datetimes normalizes to the same instant.
    """
    local = moment.astimezone(_MT_ZONE)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def is_live_stale(live_fetched_at: datetime | None, settled_fetched_at: datetime | None) -> bool:
    """True when the live TWS overlay should not be presented as current.

    Stale when the live snapshot is from a *prior Mountain-Time calendar day*
    AND a settled/Flex import exists from the live-capture day or later::

        is_live_stale =
            live_fetched_at < midnight_MT(today)              # prior MT day
            AND settled_fetched_at is not None
            AND settled_fetched_at > midnight_MT(live_day)    # fallback data exists

    The settled-import guard means we only flag the overlay stale when there is
    settled data (from the live-capture day or later) to fall back to; without a
    fallback there's nothing better to show, so the overlay is left as-is.

    Timestamps are timezone-aware (``DateTime(timezone=True)``). None-guards: no
    live snapshot → not stale; no settled snapshot → not stale.
    """
    if live_fetched_at is None or settled_fetched_at is None:
        return False
    if live_fetched_at >= _midnight_mt(datetime.now(timezone.utc)):
        return False  # live snapshot is from today's MT calendar day — fresh
    return settled_fetched_at > _midnight_mt(live_fetched_at)


def ct_date(moment: datetime) -> date:
    """America/Chicago calendar date of a tz-aware instant.

    This labels which trade date a capture belongs near, which is the sanctioned
    use of an anchor (see the repo learning on anchors vs durations: an anchor is
    correct for labeling a trade date, wrong for sizing a retention window).
    """
    return moment.astimezone(_CT_ZONE).date()


def is_overlay_superseded(live_fetched_at: datetime | None, account_as_of: date | None) -> bool:
    """True when a settled snapshot postdates a live overlay capture.

    ``account_as_of`` is the newest ``Position.as_of_date`` for the capture's
    account -- an account-level fact, so it is available even for a contract the
    snapshot omits entirely. That is the whole point: a closed position has no
    settled row to compare against, which is why the per-row ``is_live_stale``
    check cannot see it.

    The comparison is strict. A capture's own trade date can be at most one day
    ahead of its CT date, so requiring ``as_of`` to be strictly greater
    guarantees the snapshot covers the capture for any venue -- including an
    overnight futures or Blue Ocean equity fill that belongs to the next trade
    date. Erring this way keeps a still-fresh overlay row rather than deleting
    it.

    None-guards: no capture, or an account with no settled snapshot at all, is
    never superseded.
    """
    if live_fetched_at is None or account_as_of is None:
        return False
    return account_as_of > ct_date(live_fetched_at)


def superseded_cutoff(account_as_of: date) -> datetime:
    """Instant at or after which a capture is NOT superseded by ``account_as_of``.

    Set-based equivalent of :func:`is_overlay_superseded`, for use in a SQL
    ``DELETE``/filter instead of a per-row Python loop::

        account_as_of > ct_date(fetched_at)  <->  fetched_at < superseded_cutoff(account_as_of)

    Both forms must agree exactly -- ``test_intraday_overlay`` pins that.
    """
    return datetime.combine(account_as_of, time.min, tzinfo=_CT_ZONE)


def mark_if_fresh(
    mark: float | None,
    market_ts: datetime | None,
    sec_type: str | None,
    now: datetime | None = None,
) -> float | None:
    """Drop a continuously-traded instrument's mark once it is too old.

    Futures and futures options trade ~23h, so a mark from hours ago during an
    open session is stale. Equities and equity options are left alone -- their
    last print is the close and stays valid all evening.

    A capped mark behaves exactly like an absent one (the caller nulls mark_ts
    and the live unrealized alongside it); it is never replaced with the settled
    mark. ``now`` is injectable for testing.
    """
    if mark is None or market_ts is None:
        return mark
    if (sec_type or "").strip().upper() not in _CONTINUOUS_SEC_TYPES:
        return mark
    now = now or datetime.now(timezone.utc)
    if now - market_ts > CONTINUOUS_MARK_MAX_AGE:
        return None
    return mark


def parse_multiplier(value: Any) -> float:
    """Contract multiplier as a float; defaults to 1.0 when missing/invalid."""
    if value is None:
        return 1.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 1.0
    return parsed if parsed > 0 else 1.0


def compute_unrealized(qty: float, avg_cost: float, mark: float | None, multiplier: float) -> float | None:
    """Unrealized P&L per the documented multiplier-inclusive avg_cost convention."""
    if mark is None:
        return None
    return qty * mark * multiplier - qty * avg_cost


@dataclass
class PositionView:
    """Unified current-state view for one ``(account_id, con_id)``."""

    account_id: int
    con_id: int
    symbol: str | None
    local_symbol: str | None
    sec_type: str | None
    multiplier: str | None
    right: str | None
    strike: float | None
    position: float
    avg_cost: float
    # Unified mark (live quote when available, else settled snapshot mark).
    mark: float | None
    mark_ts: datetime | None
    source: str  # "live" | "settled"
    # Live-computed unrealized (None for settled-source rows).
    live_unrealized: float | None
    # Settled snapshot carry-overs (None when the instrument was opened today).
    settled_mark_price: float | None
    settled_unrealized: float | None
    settled_position_value: float | None
    as_of_date: date | None
    # Live option metrics (from the separate option_metrics.sync.tws job; None for
    # non-options or when that job hasn't run). Greeks are as returned by IBKR;
    # intrinsic/extrinsic are the read-time split of the mark (per-unit prices).
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    und_price: float | None = None
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None


def _key(account_id: int, con_id: int) -> tuple[int, int]:
    return (account_id, con_id)


def normalize_live_mark(mark: float | None, magnifier: Any) -> float | None:
    """Convert a quoted market-data price into the multiplier's price unit.

    IBKR quotes some products (e.g. grain futures) in cents while ``avg_cost``
    and the contract ``multiplier`` work in dollars; ``ContractDetails``
    ``priceMagnifier`` (100 for those, 1 otherwise) is the divisor that aligns
    them. Defaults to 1 when missing/invalid so non-magnified products are
    unchanged.
    """
    if mark is None:
        return None
    try:
        mag = float(magnifier)
    except (TypeError, ValueError):
        mag = 1.0
    if mag <= 0:
        mag = 1.0
    return mark / mag


def normalize_settled_avg_cost(avg_cost: float | None, multiplier: Any) -> float | None:
    """Convert a FlexQuery per-unit cost into the multiplier-inclusive convention.

    The two sources disagree by design. TWS ``ib.positions()`` reports ``avgCost``
    already multiplied out -- the full dollar cost of one contract -- while
    FlexQuery's ``costBasisPrice`` is a per-unit price. Every consumer of this
    field assumes the TWS convention: ``compute_unrealized`` above, and the
    frontend's Cost Basis column, all compute ``qty * avg_cost`` and read the
    result as dollars. None of them multiplies by ``multiplier``.

    So the settled value has to be normalized on the way out, or a settled-backed
    option row reports a cost basis 100x too small and a futures row 1000x too
    small. Applied at the read boundary rather than in the sync, so the stored
    column keeps matching the raw IBKR report.
    """
    if avg_cost is None:
        return None
    return avg_cost * parse_multiplier(multiplier)


_OPTION_SEC_TYPES = {"OPT", "FOP"}
_CALL_RIGHTS = {"C", "CALL"}
_PUT_RIGHTS = {"P", "PUT"}


def option_value_split(
    mark: float | None,
    right: str | None,
    strike: float | None,
    und_price: float | None,
) -> tuple[float | None, float | None]:
    """Split a per-unit option ``mark`` into ``(intrinsic, extrinsic)``.

    Intrinsic (moneyness) needs ``strike``, ``und_price``, and ``right``:
    call → ``max(0, und − strike)``, put → ``max(0, strike − und)``. Extrinsic
    (time value) is ``max(0, mark − intrinsic)``. Any of the three parts is
    ``None`` when its inputs are missing (non-option row, no underlying price, or
    no mark). Values are per-unit prices in the same unit as ``mark`` — the
    multiplier is applied only when converting to a dollar figure, per the
    documented cost-basis convention. (For price-magnified products the mark unit
    and strike/underlying unit can differ; that skew is a known follow-up, same
    family as the underlying-price fallback.)
    """
    intrinsic: float | None = None
    r = (right or "").strip().upper()
    if strike is not None and und_price is not None:
        if r in _CALL_RIGHTS:
            intrinsic = max(0.0, und_price - strike)
        elif r in _PUT_RIGHTS:
            intrinsic = max(0.0, strike - und_price)
    extrinsic = max(0.0, mark - intrinsic) if (mark is not None and intrinsic is not None) else None
    return intrinsic, extrinsic


def option_metric_fields(
    sec_type: str | None,
    right: str | None,
    strike: float | None,
    mark: float | None,
    metric: Any,
) -> dict[str, float | None]:
    """Greek + intrinsic/extrinsic fields for a view, from a metrics row.

    ``metric`` is a ``LatestOptionMetrics`` row (or None). Returns all-None for
    non-option rows so the fields stay blank in the UI.
    """
    empty: dict[str, float | None] = {k: None for k in ("iv", "delta", "gamma", "theta", "vega", "und_price", "intrinsic_value", "extrinsic_value")}
    if (sec_type or "").strip().upper() not in _OPTION_SEC_TYPES:
        return empty
    und_price = getattr(metric, "und_price", None) if metric is not None else None
    intrinsic, extrinsic = option_value_split(mark, right, strike, und_price)
    return {
        "iv": getattr(metric, "iv", None) if metric is not None else None,
        "delta": getattr(metric, "delta", None) if metric is not None else None,
        "gamma": getattr(metric, "gamma", None) if metric is not None else None,
        "theta": getattr(metric, "theta", None) if metric is not None else None,
        "vega": getattr(metric, "vega", None) if metric is not None else None,
        "und_price": und_price,
        "intrinsic_value": intrinsic,
        "extrinsic_value": extrinsic,
    }


def merge_positions(  # noqa: PLR0913
    flex_rows: list[Any],
    live_rows: list[Any],
    quotes: dict[int, Any],
    magnifiers: dict[int, Any] | None = None,
    metrics: dict[int, Any] | None = None,
    account_as_of: dict[int, date] | None = None,
) -> list[PositionView]:
    """Compose unified positions, preferring live state with FlexQuery fallback.

    - ``flex_rows``: FlexQuery ``Position`` rows (settled snapshot).
    - ``live_rows``: ``LivePosition`` rows (authoritative current state).
    - ``quotes``: ``{con_id: LatestQuote}`` live marks.
    - ``magnifiers``: ``{con_id: price_magnifier}`` to normalize quoted marks
      into the multiplier's price unit (defaults to 1 per con_id when absent).
    - ``metrics``: ``{con_id: LatestOptionMetrics}`` live greeks/IV for held
      options (from the separate ``option_metrics.sync.tws`` job). Optional; when
      absent option rows simply carry no greeks. The intrinsic/extrinsic split is
      computed here from the view's mark and the metric's underlying price.
    - ``account_as_of``: ``{account_id: newest Position.as_of_date}``. Decides
      which live captures still count as evidence of the account's current book
      (see below). Optional only for callers with no settled snapshot to compare
      against; every DB-backed caller passes ``OverlayContext.account_as_of``.

    Reconciliation per ``(account, con_id)``:
      * live present  → live qty/cost, live mark (fallback settled mark), source=live.
      * live absent, flex present, **account has a current live capture** →
        net-closed, dropped.
      * live absent, flex present, account has no current live capture →
        settled fallback.
      * flex absent, live present (opened today) → live-only row.

    "Current" is the load-bearing word in the net-closed rule. Absence from the
    overlay only proves a position was closed if the capture postdates the
    settled snapshot; a superseded capture predates every position opened since
    it, so treating it as evidence deletes held positions. ``account_as_of``
    is what separates the two, exactly as it does in ``load_overlay_context``.
    """
    flex_by_key = {_key(r.account_id, r.con_id): r for r in flex_rows}
    account_as_of = account_as_of or {}
    # Only a capture the settled snapshot has NOT superseded is evidence of what
    # the account currently holds. A stale capture cannot know about a position
    # opened after it, so counting its account here net-closes that position.
    live_accounts = {r.account_id for r in live_rows if not is_overlay_superseded(r.fetched_at, account_as_of.get(r.account_id))}
    magnifiers = magnifiers or {}
    metrics = metrics or {}
    views: list[PositionView] = []
    seen: set[tuple[int, int]] = set()

    # 1) Live-sourced rows (prefer live current state).
    for live in live_rows:
        key = _key(live.account_id, live.con_id)
        seen.add(key)
        flex = flex_by_key.get(key)
        quote = quotes.get(live.con_id)
        mult = parse_multiplier(live.multiplier)
        mark = getattr(quote, "mark", None) if quote is not None else None
        # Reject the IBKR "no data" sentinel (-1, and any non-positive price) so
        # we never compute a live PnL off a fake mark.
        if mark is not None and mark <= 0:
            mark = None
        # Normalize the quoted price into the multiplier's unit (e.g. cents →
        # dollars for grain futures) before it feeds the mark/PnL columns.
        mark = normalize_live_mark(mark, magnifiers.get(live.con_id))
        # Age out a continuously-traded instrument's mark (futures/FOP only);
        # an equity's last print is its close and stays valid.
        mark = mark_if_fresh(mark, getattr(quote, "market_ts", None), live.sec_type or (flex.sec_type if flex else None))
        # When there is no usable live mark, leave the live-specific fields null
        # (the UI shows "—" and intraday totals fall back to settled per row) —
        # do NOT mirror the settled mark into the live column.
        mark_ts = getattr(quote, "market_ts", None) if (quote is not None and mark is not None) else None
        # A stale overlay is superseded data and must not win over the newer
        # settled snapshot — the same rule the positions router applies. The row
        # is still shown (the position is held); only the numbers come from the
        # snapshot, and avg_cost is normalized into the multiplier-inclusive
        # convention the live value already uses.
        stale = is_live_stale(live.fetched_at, flex.fetched_at if flex else None)
        if stale and flex is not None:
            position, avg_cost, source = flex.position, normalize_settled_avg_cost(flex.avg_cost, flex.multiplier), "settled"
        else:
            position, avg_cost, source = live.position, live.avg_cost, "live"
        views.append(
            PositionView(
                account_id=live.account_id,
                con_id=live.con_id,
                symbol=live.symbol or (flex.symbol if flex else None),
                local_symbol=live.local_symbol or (flex.local_symbol if flex else None),
                sec_type=live.sec_type or (flex.sec_type if flex else None),
                multiplier=live.multiplier or (flex.multiplier if flex else None),
                right=live.right or (flex.right if flex else None),
                strike=live.strike if live.strike is not None else (flex.strike if flex else None),
                position=position,
                avg_cost=avg_cost,
                mark=mark,
                mark_ts=mark_ts,
                source=source,
                live_unrealized=compute_unrealized(position, avg_cost, mark, mult) if source == "live" else None,
                settled_mark_price=flex.mark_price if flex else None,
                settled_unrealized=flex.fifo_pnl_unrealized if flex else None,
                settled_position_value=flex.position_value if flex else None,
                as_of_date=flex.as_of_date if flex else None,
                **option_metric_fields(
                    live.sec_type or (flex.sec_type if flex else None),
                    live.right or (flex.right if flex else None),
                    live.strike if live.strike is not None else (flex.strike if flex else None),
                    mark,
                    metrics.get(live.con_id),
                ),
            )
        )

    # 2) Settled-only rows: keep when the account has no live data at all;
    #    drop when the account synced live but this instrument is gone (net-closed).
    for flex in flex_rows:
        key = _key(flex.account_id, flex.con_id)
        if key in seen:
            continue
        if flex.account_id in live_accounts:
            continue  # net-closed — account has a current capture, instrument absent from it
        views.append(
            PositionView(
                account_id=flex.account_id,
                con_id=flex.con_id,
                symbol=flex.symbol,
                local_symbol=flex.local_symbol,
                sec_type=flex.sec_type,
                multiplier=flex.multiplier,
                right=flex.right,
                strike=flex.strike,
                position=flex.position,
                avg_cost=normalize_settled_avg_cost(flex.avg_cost, flex.multiplier),
                mark=flex.mark_price,
                mark_ts=None,
                source="settled",
                live_unrealized=None,
                settled_mark_price=flex.mark_price,
                settled_unrealized=flex.fifo_pnl_unrealized,
                settled_position_value=flex.position_value,
                as_of_date=flex.as_of_date,
                **option_metric_fields(
                    flex.sec_type,
                    flex.right,
                    flex.strike,
                    flex.mark_price,
                    metrics.get(flex.con_id),
                ),
            )
        )

    return views


def intraday_unrealized_total(views: list[PositionView]) -> float | None:
    """Sum live unrealized where available, settled unrealized otherwise.

    With no live data this equals the settled-only total (graceful fallback).
    Returns None when no row contributes a number.
    """
    contributions = [v.live_unrealized if v.source == "live" and v.live_unrealized is not None else v.settled_unrealized for v in views]
    present = [c for c in contributions if c is not None]
    return sum(present) if present else None


def settled_unrealized_total(views: list[PositionView]) -> float | None:
    """Sum the settled snapshot unrealized (pre-overlay behavior)."""
    present = [v.settled_unrealized for v in views if v.settled_unrealized is not None]
    return sum(present) if present else None


def marks_as_of(views: list[PositionView]) -> datetime | None:
    """Newest live mark timestamp across the views, or None."""
    stamps = [v.mark_ts for v in views if v.mark_ts is not None]
    return max(stamps) if stamps else None


def dedupe_live_realized(settled_exec_ids: set[str], live_execs: list[Any]) -> tuple[list[Any], float]:
    """Drop live fills already settled (by ``ib_exec_id``); sum their realized P&L.

    Returns ``(included_live_execs, realized_sum)``. Settled wins, so a live fill
    whose ``ib_exec_id`` is already in ``settled_exec_ids`` is excluded — its
    realized P&L is counted from the settled side instead, never double-counted.
    """
    included = [e for e in live_execs if e.ib_exec_id not in settled_exec_ids]
    realized_sum = sum(e.realized_pnl for e in included if e.realized_pnl is not None)
    return included, realized_sum


@dataclass
class OverlayTotals:
    """Settled + intraday PnL totals for a set of positions."""

    settled_unrealized: float | None
    intraday_unrealized: float | None
    intraday_realized: float | None
    intraday_total: float | None
    marks_as_of: datetime | None


def overlay_totals(
    flex_rows: list[Any],
    views: list[PositionView],
    live_execs: list[Any],
    settled_exec_ids: set[str],
    realized: float | None,
) -> OverlayTotals:
    """Compose the settled + intraday PnL totals from already-merged rows.

    Single source for the trade-group / positions overlay numbers: the API
    endpoint and the tradebot ``trade_group_pnl`` tool both call this, so the
    live figures cannot diverge. ``realized`` is the settled realized PnL for the
    scope (the intraday realized adds live, not-yet-settled fills on top).
    """
    settled_vals = [p.fifo_pnl_unrealized for p in flex_rows if p.fifo_pnl_unrealized is not None]
    settled_unrealized = sum(settled_vals) if settled_vals else None

    intraday_unrealized = intraday_unrealized_total(views)
    _, live_realized = dedupe_live_realized(settled_exec_ids, live_execs)
    intraday_realized = (realized or 0.0) + live_realized if (realized is not None or live_realized) else None

    intraday_total = None
    if intraday_unrealized is not None or intraday_realized is not None:
        intraday_total = (intraday_unrealized or 0.0) + (intraday_realized or 0.0)

    return OverlayTotals(
        settled_unrealized=settled_unrealized,
        intraday_unrealized=intraday_unrealized,
        intraday_realized=intraday_realized,
        intraday_total=intraday_total,
        marks_as_of=marks_as_of(views),
    )
