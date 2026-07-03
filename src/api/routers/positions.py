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
    normalize_live_mark,
    parse_multiplier,
)
from src.services.jobs import (
    JOB_TYPE_INTRADAY_SYNC_TWS,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
    JOB_TYPE_POSITIONS_SYNC_TWS,
    enqueue_job,
)
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


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


def _derive_option_expiry_and_dte(position: Position) -> tuple[str | None, int | None]:
    sec_type = (position.sec_type or "").strip().upper()
    expiry = _parse_raw_expiry_date(position.last_trade_date)
    if expiry is None:
        return None, None

    option_expiry_date = expiry.isoformat() if sec_type in {"OPT", "FOP"} else None
    return option_expiry_date, (expiry - date.today()).days


def _account_alias(acct: Account | None, account_id: int) -> str:
    if acct:
        return acct.alias if acct.alias else f"Account Alias {acct.id}"
    return f"Unknown Account {account_id}"


@router.get("/positions", response_model=list[PositionResponse])
def list_positions(db: Session = DB_SESSION_DEPENDENCY):
    rows = db.execute(select(Position, Account).outerjoin(Account, Position.account_id == Account.id)).all()

    # Portfolio-wide live overlay (not group-scoped): live current state + marks.
    live_by_key = {(p.account_id, p.con_id): p for p in db.execute(select(LivePosition)).scalars().all()}
    quotes = {q.con_id: q for q in db.execute(select(LatestQuote)).scalars().all()}
    # price_magnifier per con_id normalizes quoted marks (e.g. cents → dollars
    # for grain futures) into the multiplier's price unit. Missing → treated as 1.
    magnifiers = dict(db.execute(select(ContractRef.con_id, ContractRef.price_magnifier)).all())
    accounts_by_id = {a.id: a for a in db.execute(select(Account)).scalars().all()}

    # Map each (account_id, con_id) to the trade group(s) it's associated with.
    # Association is always at the *execution* (fill) level — uniform across
    # FlexQuery and TWS — and rolled up here to a position. Two execution sources
    # are unioned:
    #   (1) settled fills: TradeExecution -> TradeGroupExecution (covers both
    #       FlexQuery fills and TWS fills that have settled via the trade sync);
    #   (2) live fills: LiveExecution -> TradeGroupLiveExecution, keyed by
    #       ib_exec_id, so a TWS fill is groupable intraday before it settles.
    # On settlement the live link is carried over into TradeGroupExecution, so a
    # fill is never counted from both sources. Not all positions have a group.
    trade_group_acc: dict[tuple[int, int], dict[int, TradeGroupRef]] = {}
    settled_rows = db.execute(
        select(
            TradeExecution.account_id,
            TradeExecution.con_id,
            TradeGroup.id,
            TradeGroup.name,
        )
        .join(
            TradeGroupExecution,
            TradeGroupExecution.trade_execution_id == TradeExecution.id,
        )
        .join(TradeGroup, TradeGroup.id == TradeGroupExecution.trade_group_id)
        .where(TradeExecution.con_id.is_not(None))
        .distinct()
        .order_by(TradeGroup.id.asc())
    ).all()
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
        .order_by(TradeGroup.id.asc())
    ).all()
    for account_id, con_id, group_id, group_name in [*settled_rows, *live_rows]:
        trade_group_acc.setdefault((account_id, con_id), {}).setdefault(group_id, TradeGroupRef(id=group_id, name=group_name))

    trade_group_map: dict[tuple[int, int], list[TradeGroupRef]] = {key: sorted(groups.values(), key=lambda g: g.id) for key, groups in trade_group_acc.items()}

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
        mark = None
        mark_ts = None
        live_unrealized = None
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
        results.append(
            PositionResponse(
                id=pos.id,
                account_id=pos.account_id,
                account_alias=_account_alias(acct, pos.account_id),
                contract_display_name=display_name,
                con_id=pos.con_id,
                trade_groups=trade_group_map.get((pos.account_id, pos.con_id), []),
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
        results.append(
            PositionResponse(
                id=-con_id,  # synthetic id for a live-only row (no Position PK yet)
                account_id=account_id,
                account_alias=_account_alias(accounts_by_id.get(account_id), account_id),
                contract_display_name=display_name,
                con_id=con_id,
                trade_groups=trade_group_map.get((account_id, con_id), []),
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
