"""Market data fetch services for futures and futures options."""

from __future__ import annotations

import datetime as dt
import logging
import math
from datetime import datetime, timezone
from numbers import Real
from typing import Any

from ib_async import IB, Contract
from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import (
    ContractRef,
    LatestFutures,
    LatestFuturesOptions,
    TsFutures,
    TsFuturesOptions,
)

logger = logging.getLogger(__name__)

BATCH_SIZE = 100


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, Real):
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return int(v)
    return None


def _contract_from_ref(ref: ContractRef) -> Contract:
    c = Contract(conId=ref.con_id, exchange=ref.exchange, currency=ref.currency)
    c.symbol = ref.symbol
    c.secType = ref.sec_type
    if ref.local_symbol:
        c.localSymbol = ref.local_symbol
    if ref.trading_class:
        c.tradingClass = ref.trading_class
    if ref.contract_expiry:
        c.lastTradeDateOrContractMonth = ref.contract_expiry
    if ref.multiplier:
        c.multiplier = ref.multiplier
    if ref.strike is not None:
        c.strike = ref.strike
    if ref.right:
        c.right = ref.right
    return c


def _connect(host: str, port: int, client_id: int, timeout: float = 20.0) -> IB:
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=timeout)
    except TimeoutError as exc:
        raise RuntimeError(f"Timed out connecting to TWS/Gateway (host={host}, port={port}, client_id={client_id}).") from exc
    return ib


def _fetch_tickers(ib: IB, contracts: list[Contract]) -> dict[int, object]:
    """Request snapshot tickers in batches, return mapping of con_id → ticker."""
    total = len(contracts)
    batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info("Fetching tickers for %d contracts (%d batches of %d)", total, batches, BATCH_SIZE)
    ib.reqMarketDataType(3)  # delayed-frozen if live unavailable
    by_con_id: dict[int, object] = {}
    for i in range(0, total, BATCH_SIZE):
        batch = contracts[i : i + BATCH_SIZE]
        logger.info("Requesting batch %d/%d (%d contracts)", i // BATCH_SIZE + 1, batches, len(batch))
        tickers = ib.reqTickers(*batch)
        for ticker in tickers:
            contract = getattr(ticker, "contract", None)
            con_id = getattr(contract, "conId", None)
            if isinstance(con_id, int) and con_id > 0:
                by_con_id[con_id] = ticker
    logger.info("Received %d/%d tickers", len(by_con_id), total)
    return by_con_id


def _fetch_tickers_connected(
    host: str, port: int, client_id: int, connect_timeout_seconds: float, ib: IB | None, contracts: list[Contract]
) -> dict[int, object]:
    """Fetch tickers on the caller's IB session, or connect (and disconnect) one when none is given."""
    owns_ib = ib is None
    if ib is None:
        ib = _connect(host, port, client_id, connect_timeout_seconds)
    try:
        return _fetch_tickers(ib, contracts)
    finally:
        if owns_ib and ib.isConnected():
            ib.disconnect()


def _load_future_prices(engine: Engine, fut_con_ids: set[int]) -> dict[int, float]:
    """Latest FUT price (last, else close) per con_id from latest_futures, used as a fallback und_price."""
    fut_prices: dict[int, float] = {}
    if fut_con_ids:
        with Session(engine) as session:
            rows = session.execute(
                select(LatestFutures.con_id, LatestFutures.last, LatestFutures.close).where(LatestFutures.con_id.in_(list(fut_con_ids)))
            ).all()
            for row in rows:
                price = row.last if row.last and row.last > 0 else row.close
                if price and price > 0:
                    fut_prices[row.con_id] = float(price)
    return fut_prices


def _future_fields(ticker: object) -> dict[str, Any]:
    """Quote columns shared by ts_futures and latest_futures."""
    return {
        "bid": _safe_float(getattr(ticker, "bid", None)),
        "ask": _safe_float(getattr(ticker, "ask", None)),
        "last": _safe_float(getattr(ticker, "last", None)),
        "close": _safe_float(getattr(ticker, "close", None)),
        "volume": _safe_int(getattr(ticker, "volume", None)),
        "open_interest": _safe_int(getattr(ticker, "open_interest", None)),
    }


def _write_future_row(session: Session, ref: ContractRef, fields: dict[str, Any], now: datetime) -> None:
    """Append to ts_futures, then guarded upsert into latest_futures."""
    market_ts = now
    session.add(TsFutures(con_id=ref.con_id, **fields, market_ts=market_ts, ingested_at=now))
    session.execute(
        insert(LatestFutures)
        .values(con_id=ref.con_id, **fields, market_ts=market_ts, ingested_at=now, updated_at=now)
        .on_conflict_do_update(
            index_elements=["con_id"],
            set_={**fields, "market_ts": market_ts, "ingested_at": now, "updated_at": now},
            where=LatestFutures.__table__.c.market_ts <= market_ts,
        )
    )


def _option_fields(ticker: object, ref: ContractRef, fut_prices: dict[int, float]) -> dict[str, Any]:
    """Quote and greek columns shared by ts_futures_options and latest_futures_options."""
    greeks = getattr(ticker, "modelGreeks", None)
    und_price = _safe_float(getattr(greeks, "undPrice", None)) if greeks else None

    # Fallback: use latest_futures price if IBKR didn't provide und_price
    if und_price is None and ref.underlying_con_id:
        und_price = fut_prices.get(ref.underlying_con_id)

    return {
        **_future_fields(ticker),
        "iv": _safe_float(getattr(greeks, "impliedVol", None)) if greeks else None,
        "delta": _safe_float(getattr(greeks, "delta", None)) if greeks else None,
        "gamma": _safe_float(getattr(greeks, "gamma", None)) if greeks else None,
        "theta": _safe_float(getattr(greeks, "theta", None)) if greeks else None,
        "vega": _safe_float(getattr(greeks, "vega", None)) if greeks else None,
        "und_price": und_price,
    }


def _write_option_row(session: Session, ref: ContractRef, fields: dict[str, Any], now: datetime) -> None:
    """Append to ts_futures_options, then guarded upsert into latest_futures_options."""
    market_ts = now
    session.add(TsFuturesOptions(con_id=ref.con_id, **fields, market_ts=market_ts, ingested_at=now))
    vals = {"con_id": ref.con_id, **fields, "market_ts": market_ts, "ingested_at": now, "updated_at": now}
    session.execute(
        insert(LatestFuturesOptions)
        .values(**vals)
        .on_conflict_do_update(
            index_elements=["con_id"],
            set_={k: v for k, v in vals.items() if k != "con_id"},
            where=LatestFuturesOptions.__table__.c.market_ts <= market_ts,
        )
    )


# ---------------------------------------------------------------------------
# Action 2: Fetch futures term-structure prices
# ---------------------------------------------------------------------------


def fetch_futures_prices(  # noqa: PLR0913 — public market-data signature used by callers
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    symbol: str,
    front_n: int = 6,
    connect_timeout_seconds: float = 20.0,
    ib: IB | None = None,
) -> dict:
    symbol = symbol.upper()

    with Session(engine) as session:
        refs = list(
            session.execute(
                select(ContractRef)
                .where(
                    ContractRef.symbol == symbol,
                    ContractRef.sec_type == "FUT",
                    ContractRef.is_active.is_(True),
                )
                .order_by(ContractRef.contract_expiry.asc())
                .limit(front_n)
            )
            .scalars()
            .all()
        )

    if not refs:
        return {"symbol": symbol, "contracts": 0, "rows_inserted": 0}

    contracts = [_contract_from_ref(r) for r in refs]
    owns_ib = ib is None
    if ib is None:
        ib = _connect(host, port, client_id, connect_timeout_seconds)
    try:
        by_con_id = _fetch_tickers(ib, contracts)
    finally:
        if owns_ib and ib.isConnected():
            ib.disconnect()

    now = _now_utc()
    inserted = 0

    with Session(engine) as session:
        for ref in refs:
            ticker = by_con_id.get(ref.con_id)
            if ticker is None:
                continue

            market_ts = now
            bid = _safe_float(getattr(ticker, "bid", None))
            ask = _safe_float(getattr(ticker, "ask", None))
            last = _safe_float(getattr(ticker, "last", None))
            close = _safe_float(getattr(ticker, "close", None))
            volume = _safe_int(getattr(ticker, "volume", None))
            oi = _safe_int(getattr(ticker, "open_interest", None))

            # 1. Append to ts_futures
            session.add(
                TsFutures(
                    con_id=ref.con_id,
                    bid=bid,
                    ask=ask,
                    last=last,
                    close=close,
                    volume=volume,
                    open_interest=oi,
                    market_ts=market_ts,
                    ingested_at=now,
                )
            )

            # 2. Guarded upsert into latest_futures
            stmt = (
                insert(LatestFutures)
                .values(
                    con_id=ref.con_id,
                    bid=bid,
                    ask=ask,
                    last=last,
                    close=close,
                    volume=volume,
                    open_interest=oi,
                    market_ts=market_ts,
                    ingested_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["con_id"],
                    set_={
                        "bid": bid,
                        "ask": ask,
                        "last": last,
                        "close": close,
                        "volume": volume,
                        "open_interest": oi,
                        "market_ts": market_ts,
                        "ingested_at": now,
                        "updated_at": now,
                    },
                    where=LatestFutures.__table__.c.market_ts <= market_ts,
                )
            )
            session.execute(stmt)
            inserted += 1

        session.commit()

    return {"symbol": symbol, "contracts": len(refs), "rows_inserted": inserted}


# ---------------------------------------------------------------------------
# Action 3: Fetch futures options prices + greeks
# ---------------------------------------------------------------------------


def _option_refs_stmt(
    symbol: str,
    underlying_con_id: int | None,
    strike_gte: float | None,
    strike_lte: float | None,
    dte_lte: int | None,
    right: str | None,
) -> Select[ContractRef]:
    stmt = select(ContractRef).where(
        ContractRef.symbol == symbol,
        ContractRef.sec_type == "FOP",
        ContractRef.is_active.is_(True),
    )
    if underlying_con_id is not None:
        stmt = stmt.where(ContractRef.underlying_con_id == underlying_con_id)
    if strike_gte is not None:
        stmt = stmt.where(ContractRef.strike >= strike_gte)
    if strike_lte is not None:
        stmt = stmt.where(ContractRef.strike <= strike_lte)
    if right is not None:
        stmt = stmt.where(ContractRef.right == right.upper())
    if dte_lte is not None:
        max_expiry = (dt.date.today() + dt.timedelta(days=dte_lte)).strftime("%Y%m%d")
        stmt = stmt.where(ContractRef.contract_expiry <= max_expiry)

    return stmt.order_by(ContractRef.contract_expiry.asc(), ContractRef.strike.asc())


def _apply_modulus_filter(all_refs: list[ContractRef], modulus_eq: float | None) -> list[ContractRef]:
    """Apply modulus filter in Python (not easily expressible in SQL for floats)."""
    if not (modulus_eq and modulus_eq > 0):
        return all_refs

    refs = []
    for r in all_refs:
        if r.strike is not None:
            remainder = round(r.strike % modulus_eq, 10)
            if remainder < 1e-9 or abs(remainder - modulus_eq) < 1e-9:
                refs.append(r)
        else:
            refs.append(r)
    logger.info("Modulus filter (mod=%.4f): %d → %d contracts", modulus_eq, len(all_refs), len(refs))
    return refs


def fetch_futures_options(  # noqa: PLR0913 — public job entry point; connection and filter fields are explicit
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    symbol: str,
    underlying_con_id: int | None = None,
    strike_gte: float | None = None,
    strike_lte: float | None = None,
    dte_lte: int | None = None,
    right: str | None = None,
    modulus_eq: float | None = None,
    front_n: int = 6,
    connect_timeout_seconds: float = 20.0,
    ib: IB | None = None,
) -> dict:
    symbol = symbol.upper()

    # Default modulus from option_filters config if not provided
    if modulus_eq is None:
        from src.data.option_filters import get_option_filter

        filt = get_option_filter(symbol)
        modulus_eq = filt.get("modulus_eq")

    with Session(engine) as session:
        stmt = _option_refs_stmt(symbol, underlying_con_id, strike_gte, strike_lte, dte_lte, right)
        all_refs = list(session.execute(stmt).scalars().all())

    refs = _apply_modulus_filter(all_refs, modulus_eq)

    if not refs:
        return {"symbol": symbol, "contracts": 0, "rows_inserted": 0}

    contracts = [_contract_from_ref(r) for r in refs]
    by_con_id = _fetch_tickers_connected(host, port, client_id, connect_timeout_seconds, ib, contracts)

    now = _now_utc()
    inserted = 0

    # Pre-load FUT prices from latest_futures as fallback for und_price
    fut_prices = _load_future_prices(engine, {r.underlying_con_id for r in refs if r.underlying_con_id})

    with Session(engine) as session:
        for ref in refs:
            ticker = by_con_id.get(ref.con_id)
            if ticker is None:
                continue

            if getattr(ticker, "modelGreeks", None) is None:
                logger.warning("No modelGreeks for FOP con_id=%d (%s)", ref.con_id, ref.local_symbol)

            _write_option_row(session, ref, _option_fields(ticker, ref, fut_prices), now)
            inserted += 1

        session.commit()

    return {"symbol": symbol, "contracts": len(refs), "rows_inserted": inserted}


# ---------------------------------------------------------------------------
# Action 4: Quick pre-trade snapshot
# ---------------------------------------------------------------------------


def _snapshot_option(session: Session, ref: ContractRef, ticker: object, fut_prices: dict[int, float], now: datetime) -> dict:
    fields = _option_fields(ticker, ref, fut_prices)
    _write_option_row(session, ref, fields, now)
    return {
        "con_id": ref.con_id,
        "sec_type": "FOP",
        "bid": fields["bid"],
        "ask": fields["ask"],
        "last": fields["last"],
        "iv": fields["iv"],
        "delta": fields["delta"],
        "und_price": fields["und_price"],
    }


def _snapshot_future(session: Session, ref: ContractRef, ticker: object, now: datetime) -> dict:
    # FUT or other
    fields = _future_fields(ticker)
    _write_future_row(session, ref, fields, now)
    return {
        "con_id": ref.con_id,
        "sec_type": ref.sec_type,
        "bid": fields["bid"],
        "ask": fields["ask"],
        "last": fields["last"],
    }


def fetch_snapshot(  # noqa: PLR0913 — public job entry point; connection fields are explicit
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    con_ids: list[int],
    connect_timeout_seconds: float = 20.0,
    ib: IB | None = None,
) -> dict:
    if not con_ids:
        return {"contracts": 0, "rows_inserted": 0, "results": []}

    with Session(engine) as session:
        refs = list(session.execute(select(ContractRef).where(ContractRef.con_id.in_(con_ids))).scalars().all())

    if not refs:
        return {"contracts": 0, "rows_inserted": 0, "results": []}

    contracts = [_contract_from_ref(r) for r in refs]
    by_con_id = _fetch_tickers_connected(host, port, client_id, connect_timeout_seconds, ib, contracts)

    now = _now_utc()
    inserted = 0
    results: list[dict] = []

    # Pre-load FUT prices as fallback for FOP und_price
    fop_refs = [r for r in refs if r.sec_type == "FOP"]
    snap_fut_prices = _load_future_prices(engine, {r.underlying_con_id for r in fop_refs if r.underlying_con_id})

    with Session(engine) as session:
        for ref in refs:
            ticker = by_con_id.get(ref.con_id)
            if ticker is None:
                continue

            if ref.sec_type == "FOP":
                results.append(_snapshot_option(session, ref, ticker, snap_fut_prices, now))
            else:
                results.append(_snapshot_future(session, ref, ticker, now))

            inserted += 1

        session.commit()

    return {"contracts": len(refs), "rows_inserted": inserted, "results": results}
