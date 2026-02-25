"""Fetch a single contract from IBKR and add it to a watch list."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ib_async import IB
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import ContractRef, WatchList, WatchListInstrument
from src.services.cl_contracts import (
    format_contract_month_from_expiry,
    infer_contract_month_from_local_symbol,
)
from src.services.ibkr_select_contracts import select_contract_for_watchlist

logger = logging.getLogger("services:watchlist_instrument_sync")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def fetch_and_add_instrument(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    watch_list_id: int,
    symbol: str,
    sec_type: str,
    exchange: str,
    contract_month: str | None = None,
    strike: float | None = None,
    right: str | None = None,
    connect_timeout_seconds: float = 20.0,
) -> dict:
    """Fetch a single contract from IBKR, upsert into contract_refs, and add to watch list.

    Returns a dict with instrument details.
    """
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(f"Timed out connecting to TWS/Gateway " f"(host={host}, port={port}, client_id={client_id}).") from exc

        contract, match_count = select_contract_for_watchlist(
            ib=ib,
            symbol=symbol,
            sec_type=sec_type,
            exchange=exchange,
            contract_month=contract_month,
            strike=strike,
            right=right,
        )
        if match_count > 1:
            logger.info(
                "Got %d contract matches for %s %s, selected con_id=%s",
                match_count,
                symbol,
                sec_type,
                contract.conId,
            )

        if contract is None or contract.conId is None or contract.conId == 0:
            raise RuntimeError("IBKR returned a contract with no valid conId.")

        con_id = contract.conId
        raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
        fetched_contract_month = infer_contract_month_from_local_symbol(
            local_symbol=contract.localSymbol or None,
            contract_expiry=raw_expiry,
            sec_type=contract.secType or sec_type,
        ) or format_contract_month_from_expiry(raw_expiry)
        now = _now_utc()

        # Upsert into contract_refs (same pattern as contract_sync.py)
        values = {
            "con_id": con_id,
            "symbol": contract.symbol or symbol,
            "sec_type": contract.secType or sec_type,
            "exchange": contract.exchange or exchange,
            "currency": contract.currency or "USD",
            "local_symbol": contract.localSymbol or None,
            "trading_class": contract.tradingClass or None,
            "contract_month": fetched_contract_month,
            "contract_expiry": raw_expiry,
            "multiplier": contract.multiplier or None,
            "strike": (contract.strike if contract.strike and contract.strike != 0.0 else None),
            "right": (contract.right if contract.right and contract.right != "?" else None),
            "primary_exchange": contract.primaryExchange or None,
            "is_active": True,
            "fetched_at": now,
            "updated_at": now,
        }

        with Session(engine) as session:
            # Verify watch list exists
            wl = session.get(WatchList, watch_list_id)
            if wl is None:
                raise RuntimeError(f"Watch list #{watch_list_id} not found.")

            # Upsert contract_ref
            stmt = (
                insert(ContractRef)
                .values(**values, created_at=now)
                .on_conflict_do_update(
                    index_elements=["con_id"],
                    set_={k: v for k, v in values.items() if k != "con_id"},
                )
            )
            session.execute(stmt)

            # Check for duplicate in watch_list_instruments
            existing = (
                session.execute(
                    select(WatchListInstrument).where(
                        WatchListInstrument.watch_list_id == watch_list_id,
                        WatchListInstrument.con_id == con_id,
                    )
                )
                .scalars()
                .first()
            )

            already_existed = existing is not None
            if existing is not None:
                watch_list_instrument_id = existing.id
            else:
                inst = WatchListInstrument(
                    watch_list_id=watch_list_id,
                    con_id=con_id,
                    symbol=values["symbol"],
                    sec_type=values["sec_type"],
                    exchange=values["exchange"],
                    currency=values["currency"],
                    local_symbol=values["local_symbol"],
                    trading_class=values["trading_class"],
                    contract_month=values["contract_month"],
                    contract_expiry=values["contract_expiry"],
                    multiplier=values["multiplier"],
                    strike=values["strike"],
                    right=values["right"],
                    primary_exchange=values["primary_exchange"],
                )
                session.add(inst)
                session.flush()
                watch_list_instrument_id = inst.id

            session.commit()

        return {
            "con_id": con_id,
            "symbol": values["symbol"],
            "sec_type": values["sec_type"],
            "local_symbol": values["local_symbol"],
            "contract_month": values["contract_month"],
            "contract_expiry": values["contract_expiry"],
            "strike": values["strike"],
            "right": values["right"],
            "watch_list_instrument_id": watch_list_instrument_id,
            "already_existed": already_existed,
        }
    finally:
        if ib.isConnected():
            ib.disconnect()
