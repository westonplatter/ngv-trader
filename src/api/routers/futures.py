"""Futures term-structure, options, and vol-surface endpoints."""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Query
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import (
    ContractRef,
    LatestFutures,
    LatestFuturesOptions,
    TsFutures,
)

router = APIRouter()


def _dte(contract_expiry: str | None) -> int | None:
    if not contract_expiry:
        return None
    try:
        exp = datetime.strptime(contract_expiry, "%Y%m%d").date()
        return (exp - date.today()).days
    except ValueError:
        return None


def _display_name(symbol: str, contract_month: str | None, sec_type: str, **kwargs: object) -> str:
    if sec_type == "FOP":
        strike = kwargs.get("strike")
        right = kwargs.get("right")
        trading_class = kwargs.get("trading_class")
        contract_expiry = kwargs.get("contract_expiry")
        parts = [symbol]
        if trading_class:
            parts.append(f"({trading_class})")
        if contract_month:
            parts.append(contract_month)
        elif contract_expiry:
            parts.append(str(contract_expiry))
        if strike is not None:
            parts.append(str(strike))
        if right:
            parts.append("CALL" if right == "C" else "PUT")
        return " ".join(parts)
    if contract_month:
        return f"{symbol} {contract_month}"
    return symbol


@router.get("/futures/{symbol}/term-structure")
def get_term_structure(
    symbol: str,
    front_n: int = Query(default=6, ge=1, le=24),  # noqa: B008
    as_of: datetime | None = Query(default=None),  # noqa: B008
):
    engine = get_engine()
    symbol = symbol.upper()

    with Session(engine) as session:
        if as_of is None:
            # Default path: use latest_futures
            stmt = (
                select(ContractRef, LatestFutures)
                .outerjoin(LatestFutures, LatestFutures.con_id == ContractRef.con_id)
                .where(
                    ContractRef.symbol == symbol,
                    ContractRef.sec_type == "FUT",
                    ContractRef.is_active.is_(True),
                )
                .order_by(ContractRef.contract_expiry.asc())
                .limit(front_n)
            )
            rows = session.execute(stmt).all()

            return [
                {
                    "con_id": c.con_id,
                    "symbol": c.symbol,
                    "local_symbol": c.local_symbol,
                    "display_name": _display_name(c.symbol, c.contract_month, c.sec_type),
                    "contract_expiry": c.contract_expiry,
                    "contract_month": c.contract_month,
                    "dte": _dte(c.contract_expiry),
                    "bid": lf.bid if lf else None,
                    "ask": lf.ask if lf else None,
                    "last": lf.last if lf else None,
                    "close": lf.close if lf else None,
                    "volume": lf.volume if lf else None,
                    "open_interest": lf.open_interest if lf else None,
                    "observed_at": lf.market_ts.isoformat() if lf and lf.market_ts else None,
                }
                for c, lf in rows
            ]
        else:
            # as_of path: use ts_futures history
            # Subquery to get the latest ts row per con_id <= as_of
            from sqlalchemy import func

            subq = (
                select(
                    TsFutures.con_id,
                    func.max(TsFutures.market_ts).label("max_ts"),
                )
                .where(TsFutures.market_ts <= as_of)
                .group_by(TsFutures.con_id)
                .subquery()
            )

            stmt = (
                select(ContractRef, TsFutures)
                .outerjoin(
                    subq,
                    subq.c.con_id == ContractRef.con_id,
                )
                .outerjoin(
                    TsFutures,
                    and_(
                        TsFutures.con_id == subq.c.con_id,
                        TsFutures.market_ts == subq.c.max_ts,
                    ),
                )
                .where(
                    ContractRef.symbol == symbol,
                    ContractRef.sec_type == "FUT",
                    ContractRef.is_active.is_(True),
                )
                .order_by(ContractRef.contract_expiry.asc())
                .limit(front_n)
            )
            rows = session.execute(stmt).all()

            return [
                {
                    "con_id": c.con_id,
                    "symbol": c.symbol,
                    "local_symbol": c.local_symbol,
                    "display_name": _display_name(c.symbol, c.contract_month, c.sec_type),
                    "contract_expiry": c.contract_expiry,
                    "contract_month": c.contract_month,
                    "dte": _dte(c.contract_expiry),
                    "bid": ts.bid if ts else None,
                    "ask": ts.ask if ts else None,
                    "last": ts.last if ts else None,
                    "close": ts.close if ts else None,
                    "volume": ts.volume if ts else None,
                    "open_interest": ts.open_interest if ts else None,
                    "observed_at": ts.market_ts.isoformat() if ts and ts.market_ts else None,
                }
                for c, ts in rows
            ]


def _build_options_query(
    symbol: str,
    underlying_con_id: int | None,
    underlying_month: str | None,
    strike_gte: float | None,
    strike_lte: float | None,
    right: str | None,
    dte_gte: int | None,
    dte_lte: int | None,
):
    """Build the common options query joining contracts with latest_futures_options."""
    stmt = (
        select(ContractRef, LatestFuturesOptions)
        .outerjoin(LatestFuturesOptions, LatestFuturesOptions.con_id == ContractRef.con_id)
        .where(
            ContractRef.symbol == symbol,
            ContractRef.sec_type == "FOP",
            ContractRef.is_active.is_(True),
        )
    )

    if underlying_con_id is not None:
        stmt = stmt.where(ContractRef.underlying_con_id == underlying_con_id)

    if underlying_month is not None:
        # Join to the parent FUT contract to filter by its contract_month
        from sqlalchemy.orm import aliased

        parent = aliased(ContractRef)
        stmt = stmt.join(parent, parent.con_id == ContractRef.underlying_con_id).where(parent.contract_month == underlying_month)

    if strike_gte is not None:
        stmt = stmt.where(ContractRef.strike >= strike_gte)
    if strike_lte is not None:
        stmt = stmt.where(ContractRef.strike <= strike_lte)
    if right is not None:
        stmt = stmt.where(ContractRef.right == right.upper())

    if dte_gte is not None or dte_lte is not None:
        date.today().strftime("%Y%m%d")
        if dte_gte is not None:
            from datetime import timedelta

            min_expiry = (date.today() + timedelta(days=dte_gte)).strftime("%Y%m%d")
            stmt = stmt.where(ContractRef.contract_expiry >= min_expiry)
        if dte_lte is not None:
            from datetime import timedelta

            max_expiry = (date.today() + timedelta(days=dte_lte)).strftime("%Y%m%d")
            stmt = stmt.where(ContractRef.contract_expiry <= max_expiry)

    stmt = stmt.order_by(ContractRef.contract_expiry.asc(), ContractRef.strike.asc())
    return stmt


def _format_option_row(c: ContractRef, lo: LatestFuturesOptions | None) -> dict:
    return {
        "con_id": c.con_id,
        "symbol": c.symbol,
        "display_name": _display_name(
            c.symbol,
            c.contract_month,
            c.sec_type,
            strike=c.strike,
            right=c.right,
            trading_class=c.trading_class,
            contract_expiry=c.contract_expiry,
        ),
        "sec_type": c.sec_type,
        "strike": c.strike,
        "right": c.right,
        "contract_expiry": c.contract_expiry,
        "dte": _dte(c.contract_expiry),
        "underlying_con_id": c.underlying_con_id,
        "bid": lo.bid if lo else None,
        "ask": lo.ask if lo else None,
        "last": lo.last if lo else None,
        "iv": lo.iv if lo else None,
        "delta": lo.delta if lo else None,
        "gamma": lo.gamma if lo else None,
        "theta": lo.theta if lo else None,
        "vega": lo.vega if lo else None,
        "und_price": lo.und_price if lo else None,
        "observed_at": lo.market_ts.isoformat() if lo and lo.market_ts else None,
    }


@router.get("/futures/{symbol}/chain")
def get_chain(
    symbol: str,
    underlying_con_id: int | None = Query(default=None),
    strike_gte: float | None = Query(default=None),
    strike_lte: float | None = Query(default=None),
    right: str | None = Query(default=None),
    dte_gte: int | None = Query(default=None),
    dte_lte: int | None = Query(default=None),
):
    """Return option chain catalog from option_chain_meta, enriched with
    pricing data from qualified contracts where available."""
    from datetime import timedelta

    from src.data.option_filters import is_monthly_trading_class
    from src.models import OptionChainMeta

    engine = get_engine()
    symbol = symbol.upper()

    # Query chain metadata, LEFT JOIN to ContractRef + LatestFuturesOptions
    # to get con_id and pricing for contracts that have been qualified
    stmt = (
        select(OptionChainMeta, ContractRef.con_id, LatestFuturesOptions)
        .outerjoin(
            ContractRef,
            and_(
                ContractRef.symbol == OptionChainMeta.symbol,
                ContractRef.trading_class == OptionChainMeta.trading_class,
                ContractRef.contract_expiry == OptionChainMeta.expiration,
                ContractRef.strike == OptionChainMeta.strike,
                ContractRef.right == OptionChainMeta.right,
                ContractRef.sec_type == OptionChainMeta.sec_type,
                ContractRef.is_active.is_(True),
            ),
        )
        .outerjoin(
            LatestFuturesOptions,
            LatestFuturesOptions.con_id == ContractRef.con_id,
        )
        .where(OptionChainMeta.symbol == symbol)
    )

    if underlying_con_id is not None:
        stmt = stmt.where(OptionChainMeta.underlying_con_id == underlying_con_id)
    if strike_gte is not None:
        stmt = stmt.where(OptionChainMeta.strike >= strike_gte)
    if strike_lte is not None:
        stmt = stmt.where(OptionChainMeta.strike <= strike_lte)
    if right is not None:
        stmt = stmt.where(OptionChainMeta.right == right.upper())
    if dte_gte is not None:
        min_expiry = (date.today() + timedelta(days=dte_gte)).strftime("%Y%m%d")
        stmt = stmt.where(OptionChainMeta.expiration >= min_expiry)
    if dte_lte is not None:
        max_expiry = (date.today() + timedelta(days=dte_lte)).strftime("%Y%m%d")
        stmt = stmt.where(OptionChainMeta.expiration <= max_expiry)

    stmt = stmt.order_by(
        OptionChainMeta.expiration.asc(),
        OptionChainMeta.strike.asc(),
    )

    with Session(engine) as session:
        rows = session.execute(stmt).all()
        return [
            {
                "symbol": meta.symbol,
                "trading_class": meta.trading_class,
                "expiration": meta.expiration,
                "strike": meta.strike,
                "right": meta.right,
                "dte": _dte(meta.expiration),
                "underlying_con_id": meta.underlying_con_id,
                "exchange": meta.exchange,
                "sec_type": meta.sec_type,
                "con_id": con_id,
                "display_name": _display_name(
                    meta.symbol,
                    None,
                    meta.sec_type,
                    strike=meta.strike,
                    right=meta.right,
                    trading_class=meta.trading_class,
                    contract_expiry=meta.expiration,
                ),
                "bid": lo.bid if lo else None,
                "ask": lo.ask if lo else None,
                "last": lo.last if lo else None,
                "iv": lo.iv if lo else None,
                "delta": lo.delta if lo else None,
                "is_monthly": is_monthly_trading_class(meta.symbol, meta.trading_class),
                "und_price": lo.und_price if lo else None,
                "observed_at": lo.market_ts.isoformat() if lo and lo.market_ts else None,
            }
            for meta, con_id, lo in rows
        ]


@router.get("/futures/{symbol}/options")
def get_options(
    symbol: str,
    underlying_con_id: int | None = Query(default=None),
    underlying_month: str | None = Query(default=None),
    strike_gte: float | None = Query(default=None),
    strike_lte: float | None = Query(default=None),
    right: str | None = Query(default=None),
    dte_gte: int | None = Query(default=None),
    dte_lte: int | None = Query(default=None),
):
    engine = get_engine()
    symbol = symbol.upper()

    stmt = _build_options_query(
        symbol,
        underlying_con_id,
        underlying_month,
        strike_gte,
        strike_lte,
        right,
        dte_gte,
        dte_lte,
    )

    with Session(engine) as session:
        rows = session.execute(stmt).all()
        return [_format_option_row(c, lo) for c, lo in rows]


@router.get("/futures/{symbol}/option-filter")
def get_option_filter_params(symbol: str):
    """Return computed option filter params for a symbol (strike bounds from DB prices + config)."""
    from src.data.option_filters import get_option_filter
    from src.models import LatestFutures

    engine = get_engine()
    symbol = symbol.upper()
    filt = get_option_filter(symbol)

    # Get front FUT prices from DB
    with Session(engine) as session:
        fut_rows = session.execute(
            select(ContractRef.con_id, LatestFutures.last, LatestFutures.close)
            .join(LatestFutures, LatestFutures.con_id == ContractRef.con_id)
            .where(
                ContractRef.symbol == symbol,
                ContractRef.sec_type == "FUT",
                ContractRef.is_active.is_(True),
            )
            .order_by(ContractRef.contract_expiry.asc())
            .limit(1)
        ).first()

    fut_price = None
    if fut_rows:
        fut_price = fut_rows.last if fut_rows.last and fut_rows.last > 0 else fut_rows.close
        fut_price = float(fut_price) if fut_price and fut_price > 0 else None

    # Compute strike bounds
    strike_gte = filt.get("strike_gte")
    strike_lte = filt.get("strike_lte")
    if fut_price:
        moneyness_gte = filt.get("moneyness_gte")
        moneyness_lte = filt.get("moneyness_lte")
        if moneyness_gte is not None:
            computed_gte = fut_price * (moneyness_gte / 100.0)
            strike_gte = computed_gte if strike_gte is None else max(strike_gte, computed_gte)
        if moneyness_lte is not None:
            computed_lte = fut_price * (moneyness_lte / 100.0)
            strike_lte = computed_lte if strike_lte is None else min(strike_lte, computed_lte)

    # Round to modulus if set
    modulus = filt.get("modulus_eq")
    if modulus and strike_gte is not None:
        import math

        strike_gte = math.ceil(strike_gte / modulus) * modulus
    if modulus and strike_lte is not None:
        import math

        strike_lte = math.floor(strike_lte / modulus) * modulus

    return {
        "symbol": symbol,
        "fut_price": fut_price,
        "filter_config": filt,
        "computed": {
            "strike_gte": round(strike_gte, 4) if strike_gte is not None else None,
            "strike_lte": round(strike_lte, 4) if strike_lte is not None else None,
            "dte_lte": filt.get("max_dte"),
        },
    }


@router.get("/futures/{symbol}/vol-surface")
def get_vol_surface(
    symbol: str,
    underlying_con_id: int | None = Query(default=None),
    underlying_month: str | None = Query(default=None),
    strike_gte: float | None = Query(default=None),
    strike_lte: float | None = Query(default=None),
    right: str | None = Query(default=None),
    dte_gte: int | None = Query(default=None),
    dte_lte: int | None = Query(default=None),
    expiry_start: str | None = Query(default=None),
    expiry_end: str | None = Query(default=None),
):
    engine = get_engine()
    symbol = symbol.upper()

    stmt = _build_options_query(
        symbol,
        underlying_con_id,
        underlying_month,
        strike_gte,
        strike_lte,
        right,
        dte_gte,
        dte_lte,
    )

    if expiry_start is not None:
        stmt = stmt.where(ContractRef.contract_expiry >= expiry_start.replace("-", ""))
    if expiry_end is not None:
        stmt = stmt.where(ContractRef.contract_expiry <= expiry_end.replace("-", ""))

    with Session(engine) as session:
        rows = session.execute(stmt).all()
        return [_format_option_row(c, lo) for c, lo in rows]
