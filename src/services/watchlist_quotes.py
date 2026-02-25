"""Quote refresh/read helpers for watch list instruments."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real

from ib_async import IB, Contract
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import WatchListInstrument


@dataclass(frozen=True)
class WatchListInstrumentQuote:
    instrument_id: int
    con_id: int
    bid: float | None
    ask: float | None
    close: float | None
    as_of: datetime | None


def _safe_price(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _to_contract(inst: WatchListInstrument) -> Contract:
    spec = Contract(
        conId=inst.con_id,
        symbol=inst.symbol,
        secType=inst.sec_type,
        exchange=inst.exchange,
        currency=inst.currency,
    )
    if inst.contract_expiry:
        spec.lastTradeDateOrContractMonth = inst.contract_expiry
    if inst.strike is not None:
        spec.strike = inst.strike
    if inst.right:
        spec.right = inst.right
    if inst.multiplier:
        spec.multiplier = inst.multiplier
    if inst.local_symbol:
        spec.localSymbol = inst.local_symbol
    if inst.trading_class:
        spec.tradingClass = inst.trading_class
    if inst.primary_exchange:
        spec.primaryExchange = inst.primary_exchange
    return spec


def list_watch_list_quotes(
    session: Session,
    watch_list_id: int,
) -> list[WatchListInstrumentQuote]:
    instruments = list(
        session.execute(select(WatchListInstrument).where(WatchListInstrument.watch_list_id == watch_list_id).order_by(WatchListInstrument.created_at))
        .scalars()
        .all()
    )
    return [
        WatchListInstrumentQuote(
            instrument_id=inst.id,
            con_id=inst.con_id,
            bid=inst.bid_price,
            ask=inst.ask_price,
            close=inst.close_price,
            as_of=inst.quote_as_of,
        )
        for inst in instruments
    ]


def refresh_watch_list_quotes(
    engine: Engine,
    watch_list_id: int,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 10.0,
) -> dict[str, int | str]:
    with Session(engine) as session:
        instruments = list(
            session.execute(select(WatchListInstrument).where(WatchListInstrument.watch_list_id == watch_list_id).order_by(WatchListInstrument.created_at))
            .scalars()
            .all()
        )

        if not instruments:
            return {
                "watch_list_id": watch_list_id,
                "instruments_count": 0,
                "quotes_updated": 0,
            }

        contracts = [_to_contract(inst) for inst in instruments]

        ib = IB()
        try:
            try:
                ib.connect(
                    host,
                    port,
                    clientId=client_id,
                    timeout=connect_timeout_seconds,
                )
            except Exception as exc:
                raise RuntimeError(
                    "Could not connect to TWS/Gateway while refreshing watch list quotes " f"(host={host}, port={port}, client_id={client_id}): {exc}"
                ) from exc

            ib.reqMarketDataType(3)
            try:
                tickers = ib.reqTickers(*contracts)
            except Exception as exc:
                raise RuntimeError(f"Failed to request watch list quotes from IBKR: {exc}") from exc
        finally:
            if ib.isConnected():
                ib.disconnect()

        by_con_id: dict[int, object] = {}
        for ticker in tickers:
            contract = getattr(ticker, "contract", None)
            con_id = getattr(contract, "conId", None)
            if isinstance(con_id, int) and con_id > 0:
                by_con_id[con_id] = ticker

        now = datetime.now(timezone.utc)
        updated = 0
        for inst in instruments:
            ticker = by_con_id.get(inst.con_id)
            if ticker is None:
                continue

            inst.bid_price = _safe_price(getattr(ticker, "bid", None))
            inst.ask_price = _safe_price(getattr(ticker, "ask", None))
            inst.close_price = _safe_price(getattr(ticker, "close", None))
            inst.quote_as_of = now
            updated += 1

        session.commit()
        return {
            "watch_list_id": watch_list_id,
            "instruments_count": len(instruments),
            "quotes_updated": updated,
            "as_of": now.isoformat(),
        }
