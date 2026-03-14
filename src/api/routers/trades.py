"""Trades API router."""

import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, ContractRef, Trade, TradeExecution, TradeGroupExecution
from src.services.cl_contracts import infer_contract_month_from_local_symbol
from src.services.jobs import JOB_TYPE_TRADES_SYNC, enqueue_job
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)
_MONTH_CODE_TO_MONTH = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}
_EXEC_ROLE_DISPLAY_PRIORITY = {
    "combo_summary": 0,
    "standalone": 1,
    "leg": 2,
}
_OPEN_CLOSE_DISPLAY = {
    "O": "Open",
    "OPEN": "Open",
    "OPENING": "Open",
    "TOOPEN": "Open",
    "OPENPOSITION": "Open",
    "C": "Close",
    "CLOSE": "Close",
    "CLOSING": "Close",
    "TOCLOSE": "Close",
    "CLOSEPOSITION": "Close",
}


def _parse_local_symbol_contract_month(local_symbol: str | None) -> str | None:
    if not local_symbol:
        return None
    base = local_symbol.strip().split(" ")[0].upper()
    match = re.search(r"([FGHJKMNQUVXZ])(\d{1,2})$", base)
    if match is None:
        return None
    month = _MONTH_CODE_TO_MONTH.get(match.group(1))
    if month is None:
        return None
    year_code = match.group(2)
    if len(year_code) == 2:
        year = 2000 + int(year_code)
    else:
        current_year = datetime.now().year
        decade = (current_year // 10) * 10
        digit = int(year_code)
        candidates = [decade - 10 + digit, decade + digit, decade + 10 + digit]
        year = min(candidates, key=lambda candidate: abs(candidate - current_year))
    return f"{year:04d}-{month:02d}"


def _parse_local_symbol_option_fields(local_symbol: str | None) -> tuple[str | None, float | None, str | None]:
    if not local_symbol:
        return None, None, None
    normalized = local_symbol.strip().upper()
    if not normalized:
        return None, None, None

    occ_match = re.search(r"(\d{6})([CP])(\d{8})$", normalized)
    if occ_match is not None:
        yymmdd = occ_match.group(1)
        right = occ_match.group(2)
        strike_raw = occ_match.group(3)
        contract_expiry = f"20{yymmdd[0:2]}{yymmdd[2:4]}{yymmdd[4:6]}"
        strike = int(strike_raw) / 1000
        return contract_expiry, strike, right

    parts = normalized.split()
    if len(parts) >= 2 and parts[-1][:1] in {"C", "P"} and parts[-1][1:].isdigit():
        right = parts[-1][0]
        strike_digits = parts[-1][1:]
        strike_value = int(strike_digits)
        if len(strike_digits) == 4 and strike_digits.startswith("0"):
            strike = strike_value / 1000
        elif len(strike_digits) == 4:
            strike = strike_value / 100
        else:
            strike = float(strike_value)
        return None, strike, right

    return None, None, None


def _contract_display_from_raw(  # noqa: C901, PLR0912, PLR0915
    raw: dict | None,
    contract_ref: ContractRef | None = None,
) -> str | None:
    """Extract contract display name from execution raw JSON contract payload."""
    contract = raw.get("contract") if raw else None

    expiry_raw = (contract.get("lastTradeDateOrContractMonth") or "").strip() if contract else ""
    contract_expiry: str | None = None
    contract_month: str | None = None
    if len(expiry_raw) >= 8 and expiry_raw[:8].isdigit():
        contract_expiry = expiry_raw[:8]
    elif len(expiry_raw) == 6 and expiry_raw.isdigit():
        contract_month = f"{expiry_raw[:4]}-{expiry_raw[4:6]}"

    local_symbol = (contract.get("localSymbol") or "").strip() if contract else ""
    sec_type = (contract.get("secType") or "").strip() if contract else ""
    if not local_symbol and contract_ref and contract_ref.local_symbol:
        local_symbol = contract_ref.local_symbol
    if not sec_type and contract_ref and contract_ref.sec_type:
        sec_type = contract_ref.sec_type
    if contract_month is None:
        contract_month = infer_contract_month_from_local_symbol(
            local_symbol=local_symbol or None,
            contract_expiry=contract_expiry,
            sec_type=sec_type,
        )
    if contract_month is None:
        contract_month = _parse_local_symbol_contract_month(local_symbol)

    strike_value = contract.get("strike") if contract else None
    strike: float | None = None
    if strike_value is not None:
        try:
            strike = float(strike_value)
        except (TypeError, ValueError):
            strike = None
    if strike is None and contract_ref is not None:
        strike = contract_ref.strike

    symbol = (contract.get("symbol") or "").strip() if contract else ""
    if not symbol and contract_ref and contract_ref.symbol:
        symbol = contract_ref.symbol
    right = (contract.get("right") or "").strip() if contract else ""
    if not right and contract_ref and contract_ref.right:
        right = contract_ref.right
    exchange = (contract.get("exchange") or "").strip() if contract else ""
    if not exchange and contract_ref and contract_ref.exchange:
        exchange = contract_ref.exchange
    trading_class = (contract.get("tradingClass") or "").strip() if contract else ""
    if not trading_class and contract_ref and contract_ref.trading_class:
        trading_class = contract_ref.trading_class
    if contract_expiry is None and contract_ref and contract_ref.contract_expiry:
        contract_expiry = contract_ref.contract_expiry
    if contract_month is None and contract_ref and contract_ref.contract_month:
        contract_month = contract_ref.contract_month
    parsed_expiry, parsed_strike, parsed_right = _parse_local_symbol_option_fields(local_symbol)
    if contract_expiry is None and parsed_expiry is not None:
        contract_expiry = parsed_expiry
    if strike is None and parsed_strike is not None:
        strike = parsed_strike
    if not right and parsed_right is not None:
        right = parsed_right

    if not symbol and not sec_type:
        return None

    return contract_display_name(
        symbol=symbol or None,
        sec_type=sec_type or None,
        local_symbol=local_symbol or None,
        right=right or None,
        strike=strike,
        contract_expiry=contract_expiry,
        contract_month=contract_month,
        exchange=exchange or None,
        trading_class=trading_class or None,
        include_exchange=False,
    )


def _trade_contract_display_name(trade: Trade, execution_raw: dict | None) -> str | None:
    from_execution = _contract_display_from_raw(execution_raw, None)
    if from_execution:
        return from_execution

    if not trade.symbol and not trade.sec_type:
        return None

    return contract_display_name(
        symbol=trade.symbol,
        sec_type=trade.sec_type,
        exchange=trade.exchange,
        include_exchange=False,
    )


def _execution_display_priority():
    return case(
        *[(TradeExecution.exec_role == role, priority) for role, priority in _EXEC_ROLE_DISPLAY_PRIORITY.items()],
        else_=99,
    )


def _trade_lifecycle_from_execution(raw: dict | None, exec_role: str | None) -> str | None:
    if exec_role == "combo_summary":
        return "Roll"

    execution = raw.get("execution") if raw else None
    if not isinstance(execution, dict):
        return None

    for field in ("openClose", "positionEffect"):
        value = execution.get(field)
        normalized = _OPEN_CLOSE_DISPLAY.get(str(value or "").strip().upper())
        if normalized is not None:
            return normalized
    return None


def _execution_realized_pnl(raw: dict | None) -> float | None:
    commission_report = raw.get("commissionReport") if raw else None
    if not isinstance(commission_report, dict):
        return None

    value = commission_report.get("realizedPNL")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trade_realized_pnl_from_executions(executions: list[tuple[dict | None, str | None, bool]]) -> float | None:
    canonical = [(raw, exec_role) for raw, exec_role, is_canonical in executions if is_canonical]
    if not canonical:
        return None

    combo_values = [
        realized_pnl
        for raw, exec_role in canonical
        if exec_role == "combo_summary"
        for realized_pnl in [_execution_realized_pnl(raw)]
        if realized_pnl is not None
    ]
    if combo_values:
        return sum(combo_values)

    values = [realized_pnl for raw, _ in canonical for realized_pnl in [_execution_realized_pnl(raw)] if realized_pnl is not None]
    if not values:
        return None
    return sum(values)


class TradeResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    account_alias: str | None
    contract_display_name: str | None
    lifecycle: str | None
    is_assigned: bool = False
    assigned_trade_group_id: int | None = None
    ib_perm_id: int | None
    order_ref: str | None
    ib_order_id: int | None
    symbol: str | None
    sec_type: str | None
    side: str | None
    exchange: str | None
    currency: str | None
    status: str
    total_quantity: float
    avg_price: float | None
    realized_pnl: float | None
    first_executed_at: datetime | None
    last_executed_at: datetime | None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TradeExecutionResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    trade_id: int
    account_id: int
    ib_exec_id: str
    exec_id_base: str
    exec_revision: int
    ib_perm_id: int | None
    ib_order_id: int | None
    order_ref: str | None
    sec_type: str | None
    con_id: int | None
    exec_role: str
    executed_at: datetime
    quantity: float
    price: float
    side: str | None
    exchange: str | None
    currency: str | None
    liquidity: str | None
    commission: float | None
    realized_pnl: float | None
    is_canonical: bool
    contract_display: str | None
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class TradeSyncRequest(BaseModel):
    source: str = "manual-ui"
    request_text: str | None = None
    lookback_days: int = 7
    max_attempts: int = 3


class TradeSyncResponse(BaseModel):
    job_id: int
    job_type: str
    status: str


@router.get("/trades", response_model=list[TradeResponse])
def list_trades(  # noqa: C901, PLR0912
    account_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    symbol: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    assigned_exists = (
        select(TradeGroupExecution.trade_execution_id)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .where(TradeExecution.trade_id == Trade.id)
        .exists()
    )
    stmt = select(Trade, Account, assigned_exists.label("is_assigned")).outerjoin(Account, Trade.account_id == Account.id)

    if account_id is not None:
        stmt = stmt.where(Trade.account_id == account_id)
    if status_filter is not None:
        stmt = stmt.where(Trade.status == status_filter)
    if symbol is not None:
        stmt = stmt.where(Trade.symbol == symbol.upper())

    stmt = stmt.order_by(Trade.last_executed_at.desc().nullslast()).limit(limit)
    rows = db.execute(stmt).all()
    trades = [trade for trade, _, _ in rows]
    trade_ids = [trade.id for trade in trades]

    raw_by_trade_id: dict[int, dict] = {}
    raw_exec_role_by_trade_id: dict[int, str | None] = {}
    execution_summary_by_trade_id: dict[int, list[tuple[dict | None, str | None, bool]]] = {}
    contract_ref_by_trade_id: dict[int, ContractRef] = {}
    assigned_trade_group_id_by_trade_id: dict[int, int] = {}
    if trade_ids:
        execution_rows = db.execute(
            select(
                TradeExecution.trade_id,
                TradeExecution.raw,
                TradeExecution.con_id,
                TradeExecution.exec_role,
                TradeExecution.is_canonical,
            )
            .where(TradeExecution.trade_id.in_(trade_ids))
            .order_by(
                TradeExecution.trade_id.asc(),
                _execution_display_priority(),
                TradeExecution.executed_at.desc(),
                TradeExecution.id.desc(),
            )
        ).all()
        con_ids: set[int] = set()
        for _, _, con_id, _, _ in execution_rows:
            if con_id is not None:
                con_ids.add(con_id)
        contract_ref_by_con_id: dict[int, ContractRef] = {}
        if con_ids:
            contract_ref_rows = db.execute(select(ContractRef).where(ContractRef.con_id.in_(con_ids))).scalars().all()
            contract_ref_by_con_id = {row.con_id: row for row in contract_ref_rows}

        for trade_id, raw, con_id, exec_role, is_canonical in execution_rows:
            execution_summary_by_trade_id.setdefault(trade_id, []).append(
                (raw, exec_role, is_canonical),
            )
            if trade_id not in raw_by_trade_id:
                raw_by_trade_id[trade_id] = raw
                raw_exec_role_by_trade_id[trade_id] = exec_role
                if con_id is not None and con_id in contract_ref_by_con_id:
                    contract_ref_by_trade_id[trade_id] = contract_ref_by_con_id[con_id]

        assignment_rows = db.execute(
            select(
                TradeExecution.trade_id,
                TradeGroupExecution.trade_group_id,
            )
            .join(
                TradeGroupExecution,
                TradeGroupExecution.trade_execution_id == TradeExecution.id,
            )
            .where(TradeExecution.trade_id.in_(trade_ids))
            .order_by(
                TradeExecution.trade_id.asc(),
                TradeGroupExecution.assigned_at.desc(),
                TradeGroupExecution.trade_execution_id.desc(),
            )
        ).all()
        for trade_id, trade_group_id in assignment_rows:
            if trade_id not in assigned_trade_group_id_by_trade_id:
                assigned_trade_group_id_by_trade_id[trade_id] = trade_group_id

    results = []
    for trade, acct, is_assigned in rows:
        alias = None
        if acct:
            alias = acct.alias if acct.alias else acct.account
        results.append(
            TradeResponse(
                id=trade.id,
                account_id=trade.account_id,
                account_alias=alias,
                contract_display_name=_contract_display_from_raw(
                    raw_by_trade_id.get(trade.id),
                    contract_ref_by_trade_id.get(trade.id),
                )
                or _trade_contract_display_name(trade, raw_by_trade_id.get(trade.id)),
                lifecycle=_trade_lifecycle_from_execution(
                    raw_by_trade_id.get(trade.id),
                    raw_exec_role_by_trade_id.get(trade.id),
                ),
                is_assigned=bool(is_assigned),
                assigned_trade_group_id=assigned_trade_group_id_by_trade_id.get(
                    trade.id,
                ),
                ib_perm_id=trade.ib_perm_id,
                order_ref=trade.order_ref,
                ib_order_id=trade.ib_order_id,
                symbol=trade.symbol,
                sec_type=trade.sec_type,
                side=trade.side,
                exchange=trade.exchange,
                currency=trade.currency,
                status=trade.status,
                total_quantity=trade.total_quantity,
                avg_price=trade.avg_price,
                realized_pnl=_trade_realized_pnl_from_executions(
                    execution_summary_by_trade_id.get(trade.id, []),
                ),
                first_executed_at=trade.first_executed_at,
                last_executed_at=trade.last_executed_at,
                fetched_at=trade.fetched_at,
                created_at=trade.created_at,
                updated_at=trade.updated_at,
            )
        )
    return results


@router.get("/trades/{trade_id}", response_model=TradeResponse)
def get_trade(trade_id: int, db: Session = DB_SESSION_DEPENDENCY):
    assigned_exists = (
        select(TradeGroupExecution.trade_execution_id)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .where(TradeExecution.trade_id == Trade.id)
        .exists()
    )
    stmt = select(Trade, Account, assigned_exists.label("is_assigned")).outerjoin(Account, Trade.account_id == Account.id).where(Trade.id == trade_id)
    row = db.execute(stmt).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    trade, acct, is_assigned = row
    execution_row = db.execute(
        select(TradeExecution.raw, TradeExecution.con_id, TradeExecution.exec_role)
        .where(TradeExecution.trade_id == trade_id)
        .order_by(
            _execution_display_priority(),
            TradeExecution.executed_at.desc(),
            TradeExecution.id.desc(),
        )
        .limit(1)
    ).first()
    execution_raw: dict | None = execution_row[0] if execution_row else None
    execution_con_id: int | None = execution_row[1] if execution_row else None
    execution_exec_role: str | None = execution_row[2] if execution_row else None
    contract_ref = None
    if execution_con_id is not None:
        contract_ref = db.execute(select(ContractRef).where(ContractRef.con_id == execution_con_id)).scalar_one_or_none()
    execution_summary_result = db.execute(
        select(TradeExecution.raw, TradeExecution.exec_role, TradeExecution.is_canonical)
        .where(TradeExecution.trade_id == trade_id)
        .order_by(TradeExecution.executed_at.asc(), TradeExecution.id.asc())
    ).all()
    execution_summary_rows = [(raw, exec_role, is_canonical) for raw, exec_role, is_canonical in execution_summary_result]
    assigned_trade_group_id = db.execute(
        select(TradeGroupExecution.trade_group_id)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .where(TradeExecution.trade_id == trade_id)
        .order_by(
            TradeGroupExecution.assigned_at.desc(),
            TradeGroupExecution.trade_execution_id.desc(),
        )
        .limit(1)
    ).scalar_one_or_none()
    alias = None
    if acct:
        alias = acct.alias if acct.alias else acct.account
    return TradeResponse(
        id=trade.id,
        account_id=trade.account_id,
        account_alias=alias,
        contract_display_name=_contract_display_from_raw(execution_raw, contract_ref) or _trade_contract_display_name(trade, execution_raw),
        lifecycle=_trade_lifecycle_from_execution(execution_raw, execution_exec_role),
        is_assigned=bool(is_assigned),
        assigned_trade_group_id=assigned_trade_group_id,
        ib_perm_id=trade.ib_perm_id,
        order_ref=trade.order_ref,
        ib_order_id=trade.ib_order_id,
        symbol=trade.symbol,
        sec_type=trade.sec_type,
        side=trade.side,
        exchange=trade.exchange,
        currency=trade.currency,
        status=trade.status,
        total_quantity=trade.total_quantity,
        avg_price=trade.avg_price,
        realized_pnl=_trade_realized_pnl_from_executions(execution_summary_rows),
        first_executed_at=trade.first_executed_at,
        last_executed_at=trade.last_executed_at,
        fetched_at=trade.fetched_at,
        created_at=trade.created_at,
        updated_at=trade.updated_at,
    )


@router.get("/trades/{trade_id}/executions", response_model=list[TradeExecutionResponse])
def list_trade_executions(trade_id: int, db: Session = DB_SESSION_DEPENDENCY):
    # Verify trade exists
    trade = db.get(Trade, trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")

    stmt = (
        select(TradeExecution, ContractRef)
        .outerjoin(ContractRef, ContractRef.con_id == TradeExecution.con_id)
        .where(TradeExecution.trade_id == trade_id)
        .order_by(TradeExecution.executed_at.asc())
    )
    executions = db.execute(stmt).all()
    return [
        TradeExecutionResponse(
            id=ex.id,
            trade_id=ex.trade_id,
            account_id=ex.account_id,
            ib_exec_id=ex.ib_exec_id,
            exec_id_base=ex.exec_id_base,
            exec_revision=ex.exec_revision,
            ib_perm_id=ex.ib_perm_id,
            ib_order_id=ex.ib_order_id,
            order_ref=ex.order_ref,
            sec_type=ex.sec_type,
            con_id=ex.con_id,
            exec_role=ex.exec_role,
            executed_at=ex.executed_at,
            quantity=ex.quantity,
            price=ex.price,
            side=ex.side,
            exchange=ex.exchange,
            currency=ex.currency,
            liquidity=ex.liquidity,
            commission=ex.commission,
            realized_pnl=_execution_realized_pnl(ex.raw),
            is_canonical=ex.is_canonical,
            contract_display=_contract_display_from_raw(ex.raw, contract_ref),
            fetched_at=ex.fetched_at,
            created_at=ex.created_at,
            updated_at=ex.updated_at,
        )
        for ex, contract_ref in executions
    ]


@router.post("/trades/sync", response_model=TradeSyncResponse, status_code=status.HTTP_202_ACCEPTED)
def enqueue_trades_sync(
    body: TradeSyncRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    request_text = body.request_text or "Manual trades sync."
    job = enqueue_job(
        session=db,
        job_type=JOB_TYPE_TRADES_SYNC,
        payload={"lookback_days": body.lookback_days},
        source=body.source,
        request_text=request_text,
        max_attempts=body.max_attempts,
    )
    db.commit()
    return TradeSyncResponse(
        job_id=job.id,
        job_type=job.job_type,
        status=job.status,
    )
