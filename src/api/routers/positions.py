"""Positions API router."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import (
    Account,
    ContractRef,
    LatestOptionMetrics,
    LatestQuote,
    LivePosition,
    Position,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
    TradeGroupLiveExecution,
)
from src.services.cl_contracts import infer_contract_month_from_local_symbol
from src.services.intraday_overlay import (
    compute_unrealized,
    is_live_stale,
    normalize_live_mark,
    option_metric_fields,
    parse_multiplier,
)
from src.services.jobs import (
    JOB_TYPE_INTRADAY_SYNC_TWS,
    JOB_TYPE_OPTION_METRICS_SYNC_TWS,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
    JOB_TYPE_POSITIONS_SYNC_TWS,
    enqueue_job,
)
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

# Fill quantities are floats; treat anything under this as flat.
_QTY_EPSILON = 1e-9


class TradeGroupRef(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    name: str


class PositionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str
    contract_display_name: str
    con_id: int
    trade_groups: list[TradeGroupRef]
    symbol: str | None
    sec_type: str | None
    exchange: str | None
    primary_exchange: str | None
    currency: str | None
    local_symbol: str | None
    trading_class: str | None
    last_trade_date: str | None
    option_expiry_date: str | None
    dte: int | None
    strike: float | None
    right: str | None
    multiplier: str | None
    position: float
    avg_cost: float
    mark_price: float | None
    position_value: float | None
    fifo_pnl_unrealized: float | None
    data_source: str
    as_of_date: date | None
    fetched_at: datetime
    # Intraday overlay (additive): live current-state fields.
    source: str = "settled"  # "live" | "settled"
    mark: float | None = None
    mark_ts: datetime | None = None
    live_unrealized: float | None = None
    # Staleness of the live TWS overlay — see ``is_live_stale``. True when the
    # live snapshot is from a prior Mountain-Time calendar day and a settled
    # FlexQuery import exists to fall back to. The frontend uses this to render
    # the freshness badge as "stale" (not green "live") and to blank the live
    # overlay columns.
    live_fetched_at: datetime | None = None
    live_is_stale: bool = False
    # Live option metrics (additive; from the separate option-metrics sync job).
    # None for non-options or when that job hasn't run.
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    und_price: float | None = None
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None


class PositionSyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class FlexPositionSyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    account_code: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class IntradaySyncRequest(BaseModel):
    source: str = Field(default="manual-ui", min_length=1)
    request_text: str | None = None
    account_code: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=10)


class PositionSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str
    max_attempts: int


def _parse_raw_expiry_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    digits = value.replace("-", "")
    if len(digits) >= 8 and digits[:8].isdigit():
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _option_expiry_and_dte(sec_type: str | None, raw_expiry: str | None) -> tuple[str | None, int | None]:
    """Expiry/DTE from raw values, for callers with no settled ``Position`` row.

    A position opened intraday has no FlexQuery snapshot, so its expiry has to
    come from elsewhere (the security master). Taking the two fields directly
    lets those callers reuse this rule instead of reimplementing it.
    """
    stype = (sec_type or "").strip().upper()
    expiry = _parse_raw_expiry_date(raw_expiry)
    if expiry is None:
        return None, None

    option_expiry_date = expiry.isoformat() if stype in {"OPT", "FOP"} else None
    return option_expiry_date, (expiry - date.today()).days


def _derive_option_expiry_and_dte(position: Position) -> tuple[str | None, int | None]:
    return _option_expiry_and_dte(position.sec_type, position.last_trade_date)


def _account_alias(acct: Account | None, account_id: int) -> str:
    if acct:
        return acct.alias if acct.alias else f"Account Alias {acct.id}"
    return f"Unknown Account {account_id}"


def _apply_fill_fifo(lots: list[list], quantity: float, group: TradeGroupRef | None) -> None:
    """Match one signed fill against ``lots`` FIFO, mutating it in place.

    Opposite-signed quantity closes the oldest lots first; whatever is left over
    opens a new lot carrying this fill's group (``None`` for an untagged fill).
    """
    remaining = quantity
    while abs(remaining) >= _QTY_EPSILON and lots and (lots[0][0] > 0) != (remaining > 0):
        matched = min(abs(remaining), abs(lots[0][0]))
        lots[0][0] -= matched if lots[0][0] > 0 else -matched
        remaining -= matched if remaining > 0 else -matched
        if abs(lots[0][0]) < _QTY_EPSILON:
            lots.pop(0)
    if abs(remaining) >= _QTY_EPSILON:
        lots.append([remaining, group])


def _open_lot_trade_groups(db: Session) -> tuple[
    dict[tuple[int, int], list[TradeGroupRef]],
    dict[tuple[int, int], list[TradeGroupRef]],
]:
    """Trade groups per ``(account_id, con_id)``, attributed to the *open* lots.

    A position row should carry the group(s) of the fills that actually make up
    the quantity held right now — not every group the instrument has ever passed
    through. The same con_id is routinely re-entered under a new campaign after
    an earlier one was closed out (e.g. MNQ traded flat under a covered-call
    group, then re-opened under a long-risk group); rolling up all historical
    fills stacks a chip for each of those dead campaigns onto the live row.

    So walk every fill for the instrument in execution order and match closing
    quantity against open quantity FIFO. Whatever survives the walk is the open
    lot set, and only those lots' groups are attributed to the position.
    Ungrouped fills take part in the matching (they consume open quantity) but
    contribute no chip.

    Returns ``(open_lot_map, all_fills_map)``. The second is the unfiltered
    rollup, kept as a fallback for positions whose fill history is incomplete —
    e.g. transferred-in lots that predate the sync window, where FIFO would
    close out the whole history and leave nothing to attribute.
    """
    rows = db.execute(
        select(
            TradeExecution.account_id,
            TradeExecution.con_id,
            TradeExecution.quantity,
            TradeGroup.id,
            TradeGroup.name,
        )
        .select_from(TradeExecution)
        .outerjoin(
            TradeGroupExecution,
            TradeGroupExecution.trade_execution_id == TradeExecution.id,
        )
        .outerjoin(TradeGroup, TradeGroup.id == TradeGroupExecution.trade_group_id)
        .where(TradeExecution.con_id.is_not(None))
        .order_by(
            TradeExecution.account_id.asc(),
            TradeExecution.con_id.asc(),
            TradeExecution.executed_at.asc(),
            TradeExecution.id.asc(),
        )
    ).all()

    # Per instrument: the FIFO queue of still-open lots, plus every group seen.
    open_lots: dict[tuple[int, int], list[list]] = {}
    all_groups: dict[tuple[int, int], dict[int, TradeGroupRef]] = {}
    for account_id, con_id, quantity, group_id, group_name in rows:
        key = (account_id, con_id)
        group = None
        if group_id is not None:
            group = TradeGroupRef(id=group_id, name=group_name)
            all_groups.setdefault(key, {}).setdefault(group_id, group)

        # `quantity` is already signed (BUY positive, SELL negative).
        _apply_fill_fifo(open_lots.setdefault(key, []), float(quantity or 0.0), group)

    open_map: dict[tuple[int, int], dict[int, TradeGroupRef]] = {}
    for key, lots in open_lots.items():
        for _, group in lots:
            if group is not None:
                open_map.setdefault(key, {}).setdefault(group.id, group)

    # Unsettled TWS fills are open by definition, so their groups always count.
    live_rows = db.execute(
        select(
            TradeGroupLiveExecution.account_id,
            TradeGroupLiveExecution.con_id,
            TradeGroup.id,
            TradeGroup.name,
        )
        .join(TradeGroup, TradeGroup.id == TradeGroupLiveExecution.trade_group_id)
        .where(TradeGroupLiveExecution.con_id.is_not(None))
        .distinct()
    ).all()
    for account_id, con_id, group_id, group_name in live_rows:
        key = (account_id, con_id)
        group = TradeGroupRef(id=group_id, name=group_name)
        open_map.setdefault(key, {}).setdefault(group_id, group)
        all_groups.setdefault(key, {}).setdefault(group_id, group)

    def _sorted(source: dict[tuple[int, int], dict[int, TradeGroupRef]]):
        return {key: sorted(groups.values(), key=lambda g: g.id) for key, groups in source.items()}

    return _sorted(open_map), _sorted(all_groups)


def _groups_for(
    key: tuple[int, int],
    open_map: dict[tuple[int, int], list[TradeGroupRef]],
    all_map: dict[tuple[int, int], list[TradeGroupRef]],
) -> list[TradeGroupRef]:
    """Open-lot groups, falling back to the full history when they come up empty.

    An empty open-lot set for a position that is actually held means the fill
    history does not reconcile (transferred-in lots, fills predating the sync
    window). Showing the historical rollup there is better than showing nothing.
    """
    groups = open_map.get(key)
    if groups:
        return groups
    return all_map.get(key, [])


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(db: Session = DB_SESSION_DEPENDENCY):
    rows = db.execute(select(Position, Account).outerjoin(Account, Position.account_id == Account.id)).all()

    # Portfolio-wide live overlay (not group-scoped): live current state + marks.
    live_by_key = {(p.account_id, p.con_id): p for p in db.execute(select(LivePosition)).scalars().all()}
    quotes = {q.con_id: q for q in db.execute(select(LatestQuote)).scalars().all()}
    # Live greeks/IV per con_id from the separate option-metrics sync job.
    metrics = {m.con_id: m for m in db.execute(select(LatestOptionMetrics)).scalars().all()}
    # price_magnifier per con_id normalizes quoted marks (e.g. cents → dollars
    # for grain futures) into the multiplier's price unit. Missing → treated as 1.
    magnifiers = dict(db.execute(select(ContractRef.con_id, ContractRef.price_magnifier)).all())
    accounts_by_id = {a.id: a for a in db.execute(select(Account)).scalars().all()}

    # Trade groups are attributed to the fills that make up the *currently
    # open* quantity, not to every fill the instrument has ever seen. See
    # _open_lot_trade_groups. all_group_map is the unfiltered rollup, used
    # only where the open-lot walk comes up empty for a live position.
    trade_group_map, all_group_map = _open_lot_trade_groups(db)

    results: list[PositionResponse] = []
    flex_keys: set[tuple[int, int]] = set()
    for pos, acct in rows:
        flex_keys.add((pos.account_id, pos.con_id))
        option_expiry_date, dte = _derive_option_expiry_and_dte(pos)
        inferred_month = infer_contract_month_from_local_symbol(
            local_symbol=pos.local_symbol,
            contract_expiry=pos.last_trade_date,
            sec_type=pos.sec_type,
        )
        display_name = contract_display_name(
            symbol=pos.symbol,
            sec_type=pos.sec_type,
            local_symbol=pos.local_symbol,
            right=pos.right,
            strike=pos.strike,
            contract_expiry=pos.last_trade_date,
            contract_month=inferred_month,
            exchange=pos.exchange,
            trading_class=pos.trading_class,
        )
        live = live_by_key.get((pos.account_id, pos.con_id))
        # Prefer live current state; fall back to the settled snapshot.
        position_qty = pos.position
        avg_cost = pos.avg_cost
        source = "settled"
        mark = mark_ts = live_unrealized = live_fetched_at = None
        live_is_stale = False
        if live is not None:
            quote = quotes.get(pos.con_id)
            mark = getattr(quote, "mark", None) if quote is not None else None
            # Reject the IBKR no-data sentinel; leave the live mark null when
            # there's no usable live price (no settled-mark fallback in the
            # live-specific column).
            if mark is not None and mark <= 0:
                mark = None
            mark = normalize_live_mark(mark, magnifiers.get(pos.con_id))
            mark_ts = getattr(quote, "market_ts", None) if (quote is not None and mark is not None) else None
            position_qty = live.position
            avg_cost = live.avg_cost
            source = "live"
            live_unrealized = compute_unrealized(live.position, live.avg_cost, mark, parse_multiplier(live.multiplier))
            live_fetched_at = live.fetched_at
            # Stale when the live snapshot is from a prior MT day and settled
            # data exists to fall back to (see ``is_live_stale``).
            live_is_stale = is_live_stale(live.fetched_at, pos.fetched_at)
        # Option metrics: split off the best available mark (live, else settled).
        opt_fields = option_metric_fields(
            pos.sec_type,
            pos.right,
            pos.strike,
            mark if mark is not None else pos.mark_price,
            metrics.get(pos.con_id),
        )
        results.append(
            PositionResponse(
                id=pos.id,
                account_id=pos.account_id,
                account_alias=_account_alias(acct, pos.account_id),
                contract_display_name=display_name,
                con_id=pos.con_id,
                trade_groups=_groups_for((pos.account_id, pos.con_id), trade_group_map, all_group_map),
                symbol=pos.symbol,
                sec_type=pos.sec_type,
                exchange=pos.exchange,
                primary_exchange=pos.primary_exchange,
                currency=pos.currency,
                local_symbol=pos.local_symbol,
                trading_class=pos.trading_class,
                last_trade_date=pos.last_trade_date,
                option_expiry_date=option_expiry_date,
                dte=dte,
                strike=pos.strike,
                right=pos.right,
                multiplier=pos.multiplier,
                position=position_qty,
                avg_cost=avg_cost,
                mark_price=pos.mark_price,
                position_value=pos.position_value,
                fifo_pnl_unrealized=pos.fifo_pnl_unrealized,
                data_source=pos.data_source,
                as_of_date=pos.as_of_date,
                fetched_at=pos.fetched_at,
                source=source,
                mark=mark,
                mark_ts=mark_ts,
                live_unrealized=live_unrealized,
                live_fetched_at=live_fetched_at,
                live_is_stale=live_is_stale,
                **opt_fields,
            )
        )

    # Opened-today positions: present live but with no settled snapshot row yet.
    for (account_id, con_id), live in live_by_key.items():
        if (account_id, con_id) in flex_keys or live.position == 0:
            continue
        quote = quotes.get(con_id)
        mark = getattr(quote, "mark", None) if quote is not None else None
        if mark is not None and mark <= 0:
            mark = None
        mark = normalize_live_mark(mark, magnifiers.get(con_id))
        mark_ts = getattr(quote, "market_ts", None) if (quote is not None and mark is not None) else None
        display_name = contract_display_name(
            symbol=live.symbol,
            sec_type=live.sec_type,
            local_symbol=live.local_symbol,
            right=live.right,
            strike=live.strike,
            contract_expiry=None,
            contract_month=None,
            exchange=None,
            trading_class=None,
        )
        opt_fields = option_metric_fields(live.sec_type, live.right, live.strike, mark, metrics.get(con_id))
        results.append(
            PositionResponse(
                id=-con_id,  # synthetic id for a live-only row (no Position PK yet)
                account_id=account_id,
                account_alias=_account_alias(accounts_by_id.get(account_id), account_id),
                contract_display_name=display_name,
                con_id=con_id,
                trade_groups=_groups_for((account_id, con_id), trade_group_map, all_group_map),
                symbol=live.symbol,
                sec_type=live.sec_type,
                exchange=None,
                primary_exchange=None,
                currency=None,
                local_symbol=live.local_symbol,
                trading_class=None,
                last_trade_date=None,
                option_expiry_date=None,
                dte=None,
                strike=live.strike,
                right=live.right,
                multiplier=live.multiplier,
                position=live.position,
                avg_cost=live.avg_cost,
                mark_price=None,
                position_value=None,
                fifo_pnl_unrealized=None,
                data_source="tws-live",
                as_of_date=None,
                fetched_at=live.fetched_at,
                source="live",
                mark=mark,
                mark_ts=mark_ts,
                live_unrealized=compute_unrealized(
                    live.position,
                    live.avg_cost,
                    mark,
                    parse_multiplier(live.multiplier),
                ),
                # Opened-today live-only row: no settled snapshot to fall back
                # to, so never stale (settled ts is None → is_live_stale False).
                live_fetched_at=live.fetched_at,
                live_is_stale=is_live_stale(live.fetched_at, None),
                **opt_fields,
            )
        )

    return results


@router.post(
    "/positions/sync/tws",
    response_model=PositionSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_positions_sync(
    body: PositionSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> PositionSyncResponse:
    request_text = body.request_text or "Manual positions sync from UI."
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_POSITIONS_SYNC_TWS,
        payload={},
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    return PositionSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )


@router.post(
    "/positions/sync/intraday-tws",
    response_model=PositionSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_intraday_sync(
    body: IntradaySyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> PositionSyncResponse:
    """Enqueue the intraday TWS overlay sync (live positions + marks + fills)."""
    payload: dict[str, object] = {}
    if body.account_code:
        payload["account_code"] = body.account_code
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_INTRADAY_SYNC_TWS,
        payload=payload,
        source=body.source,
        request_text=body.request_text or "Manual intraday TWS overlay sync from UI.",
        max_attempts=body.max_attempts,
    )
    db.commit()
    return PositionSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )


@router.post(
    "/positions/sync/option-metrics-tws",
    response_model=PositionSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_option_metrics_sync(
    body: IntradaySyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> PositionSyncResponse:
    """Enqueue the option-metrics TWS sync (live greeks/IV for held options).

    Separate job from the intraday mark sync so the two run independently.
    """
    payload: dict[str, object] = {}
    if body.account_code:
        payload["account_code"] = body.account_code
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_OPTION_METRICS_SYNC_TWS,
        payload=payload,
        source=body.source,
        request_text=body.request_text or "Manual option-metrics TWS sync from UI.",
        max_attempts=body.max_attempts,
    )
    db.commit()
    return PositionSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )


@router.post(
    "/positions/sync/flex-query",
    response_model=PositionSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_flex_positions_sync(
    body: FlexPositionSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
) -> PositionSyncResponse:
    payload: dict[str, object] = {}
    if body.account_code:
        payload["account_code"] = body.account_code
    if body.start_date and body.end_date:
        payload["start_date"] = body.start_date
        payload["end_date"] = body.end_date
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
        payload=payload,
        source=body.source,
        request_text=body.request_text or "Manual flex positions sync.",
        max_attempts=body.max_attempts,
    )
    db.commit()
    return PositionSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
        max_attempts=job.max_attempts,
    )
