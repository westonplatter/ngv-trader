"""Sync contract details from IBKR into the contracts table."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ib_async import IB, Contract
from ib_async import Index as IbIndex
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import ContractRef
from src.services.cl_contracts import (
    format_contract_month_from_expiry,
    infer_contract_month_from_local_symbol,
)

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sync_contracts(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    specs: list[Contract],
    connect_timeout_seconds: float = 20.0,
) -> dict:
    """Fetch contract details from IB for each spec and upsert into the contracts table.

    Returns a summary dict with counts.
    """
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(f"Timed out connecting to TWS/Gateway for contract sync " f"(host={host}, port={port}, client_id={client_id}).") from exc
        return sync_contracts_with_ib(
            engine=engine,
            ib=ib,
            specs=specs,
        )
    finally:
        if ib.isConnected():
            ib.disconnect()


def sync_contracts_with_ib(
    engine: Engine,
    *,
    ib: IB,
    specs: list[Contract],
) -> dict:
    all_con_ids: set[int] = set()
    synced_count = 0
    now = _now_utc()

    for spec in specs:
        contract_details = ib.reqContractDetails(spec)
        if not contract_details:
            continue

        spec_con_ids: set[int] = set()

        with Session(engine) as session:
            for detail in contract_details:
                contract = detail.contract
                if contract is None or contract.conId is None or contract.conId == 0:
                    continue

                raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
                contract_month = infer_contract_month_from_local_symbol(
                    local_symbol=contract.localSymbol or None,
                    contract_expiry=raw_expiry,
                    sec_type=contract.secType or spec.secType or "FUT",
                ) or format_contract_month_from_expiry(raw_expiry)

                # Determine underlying_con_id from IBKR's underConId if present
                under_con_id_raw = getattr(detail, "underConId", None) or getattr(contract, "underConId", None)
                underlying_con_id = int(under_con_id_raw) if under_con_id_raw and int(under_con_id_raw) != 0 else None

                values = {
                    "con_id": contract.conId,
                    "symbol": contract.symbol or spec.symbol or "UNKNOWN",
                    "sec_type": contract.secType or spec.secType or "FUT",
                    "exchange": contract.exchange or spec.exchange or "SMART",
                    "currency": contract.currency or spec.currency or "USD",
                    "local_symbol": contract.localSymbol or None,
                    "trading_class": contract.tradingClass or None,
                    "contract_month": contract_month,
                    "contract_expiry": raw_expiry,
                    "multiplier": contract.multiplier or None,
                    "strike": (contract.strike if contract.strike and contract.strike != 0.0 else None),
                    "right": (contract.right if contract.right and contract.right != "?" else None),
                    "primary_exchange": contract.primaryExchange or None,
                    "underlying_con_id": underlying_con_id,
                    "is_active": True,
                    "fetched_at": now,
                    "updated_at": now,
                }

                stmt = (
                    insert(ContractRef)
                    .values(**values, created_at=now)
                    .on_conflict_do_update(
                        index_elements=["con_id"],
                        set_={k: v for k, v in values.items() if k != "con_id"},
                    )
                )
                session.execute(stmt)
                spec_con_ids.add(contract.conId)
                synced_count += 1

            # Mark contracts for this spec that were NOT returned as inactive
            if spec_con_ids:
                from sqlalchemy import update

                session.execute(
                    update(ContractRef)
                    .where(
                        ContractRef.symbol == (spec.symbol or "UNKNOWN"),
                        ContractRef.sec_type == (spec.secType or "FUT"),
                        ContractRef.is_active.is_(True),
                        ContractRef.con_id.not_in(spec_con_ids),
                    )
                    .values(is_active=False, updated_at=now)
                )

            session.commit()

        all_con_ids.update(spec_con_ids)

    return {
        "synced_count": synced_count,
        "unique_con_ids": len(all_con_ids),
        "specs_count": len(specs),
    }


def _upsert_contract(
    session: Session,
    detail: Any,
    spec_symbol: str,
    spec_sec_type: str,
    spec_exchange: str,
    spec_currency: str,
    underlying_con_id: int | None,
    now: datetime,
) -> int | None:
    """Upsert a single contract detail row. Returns con_id or None if skipped."""
    contract = detail.contract
    if contract is None or contract.conId is None or contract.conId == 0:
        return None

    raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
    contract_month = infer_contract_month_from_local_symbol(
        local_symbol=contract.localSymbol or None,
        contract_expiry=raw_expiry,
        sec_type=contract.secType or spec_sec_type,
    ) or format_contract_month_from_expiry(raw_expiry)

    # Use IBKR's underConId if available, otherwise the caller-provided value
    ibkr_under = getattr(detail, "underConId", None) or getattr(contract, "underConId", None)
    if ibkr_under and int(ibkr_under) != 0:
        underlying_con_id = int(ibkr_under)

    values = {
        "con_id": contract.conId,
        "symbol": contract.symbol or spec_symbol,
        "sec_type": contract.secType or spec_sec_type,
        "exchange": contract.exchange or spec_exchange,
        "currency": contract.currency or spec_currency,
        "local_symbol": contract.localSymbol or None,
        "trading_class": contract.tradingClass or None,
        "contract_month": contract_month,
        "contract_expiry": raw_expiry,
        "multiplier": contract.multiplier or None,
        "strike": (contract.strike if contract.strike and contract.strike != 0.0 else None),
        "right": (contract.right if contract.right and contract.right != "?" else None),
        "primary_exchange": contract.primaryExchange or None,
        "underlying_con_id": underlying_con_id,
        "is_active": True,
        "fetched_at": now,
        "updated_at": now,
    }

    stmt = (
        insert(ContractRef)
        .values(**values, created_at=now)
        .on_conflict_do_update(
            index_elements=["con_id"],
            set_={k: v for k, v in values.items() if k != "con_id"},
        )
    )
    session.execute(stmt)
    return contract.conId


BATCH_SIZE = 100


def _passes_strike_filter(
    strike: float,
    fut_price: float | None,
    filt: dict,
) -> bool:
    """Check if a strike passes the filter config (moneyness, absolute bounds, modulus)."""
    # Absolute strike bounds
    strike_gte = filt.get("strike_gte")
    strike_lte = filt.get("strike_lte")
    if strike_gte is not None and strike < strike_gte:
        return False
    if strike_lte is not None and strike > strike_lte:
        return False

    # Moneyness bounds (percentage of underlying price)
    if fut_price and fut_price > 0:
        moneyness = (strike / fut_price) * 100.0
        moneyness_gte = filt.get("moneyness_gte")
        moneyness_lte = filt.get("moneyness_lte")
        if moneyness_gte is not None and moneyness < moneyness_gte:
            return False
        if moneyness_lte is not None and moneyness > moneyness_lte:
            return False

    # Modulus filter (e.g., only strikes at 0.5 increments)
    modulus_eq = filt.get("modulus_eq")
    if modulus_eq is not None and modulus_eq > 0:
        remainder = round(strike % modulus_eq, 10)
        if remainder > 1e-9 and abs(remainder - modulus_eq) > 1e-9:
            return False

    return True


def sync_futures_chain(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    symbol: str,
    exchange: str,
    currency: str = "USD",
    front_n: int = 12,
    connect_timeout_seconds: float = 20.0,
    ib: IB | None = None,
) -> dict:
    """3-step IND → FUT → chain metadata discovery and sync.

    1. Qualify the Index contract
    2. Discover the option chain via reqSecDefOptParams
    3. Sync FUT contracts (limited to front_n)
    4. Bulk-insert all chain metadata into option_chain_meta (no IBKR qualification)

    Actual FOP contract qualification happens on-demand via the
    contracts.qualify_and_snapshot job when a user selects a specific option.
    """
    owns_ib = ib is None
    if ib is None:
        ib = IB()
    try:
        if owns_ib:
            try:
                ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
            except TimeoutError as exc:
                raise RuntimeError(f"Timed out connecting to TWS/Gateway (host={host}, port={port}, client_id={client_id}).") from exc

        now = _now_utc()
        counts = {"ind": 0, "fut": 0, "fop": 0}

        # Step 1: Qualify the Index
        index = IbIndex(symbol, exchange, currency=currency)
        qualified = ib.qualifyContracts(index)
        if not qualified:
            raise RuntimeError(f"Could not qualify Index contract for {symbol} on {exchange}")
        index = qualified[0]
        index_con_id = index.conId

        # Upsert the Index contract
        index_details = ib.reqContractDetails(index)
        with Session(engine) as session:
            for detail in index_details:
                cid = _upsert_contract(
                    session,
                    detail,
                    symbol,
                    "IND",
                    exchange,
                    currency,
                    underlying_con_id=None,
                    now=now,
                )
                if cid:
                    counts["ind"] += 1
            session.commit()

        logger.info("Synced Index %s con_id=%d", symbol, index_con_id)

        # Step 2: Discover the option chain
        chains = ib.reqSecDefOptParams(
            underlyingSymbol=symbol,
            futFopExchange=exchange,
            underlyingSecType="IND",
            underlyingConId=index_con_id,
        )
        if not chains:
            logger.warning("No option chains returned for %s Index con_id=%d", symbol, index_con_id)
            return {"symbol": symbol, **counts}

        # Collect unique FUT con_ids from chain results
        # Note: ib_async returns underlyingConId as str, not int
        fut_con_ids: set[int] = set()
        chain_info: list[dict] = []
        for chain in chains:
            fut_cid_raw = getattr(chain, "underlyingConId", None)
            try:
                fut_cid = int(fut_cid_raw) if fut_cid_raw else 0
            except (ValueError, TypeError):
                fut_cid = 0
            if fut_cid != 0:
                fut_con_ids.add(fut_cid)
                chain_info.append(
                    {
                        "fut_con_id": fut_cid,
                        "trading_class": getattr(chain, "tradingClass", None),
                        "expirations": set(getattr(chain, "expirations", set())),
                        "strikes": set(getattr(chain, "strikes", set())),
                    }
                )

        logger.info("Chain discovery found %d FUT underlyings for %s", len(fut_con_ids), symbol)

        # Step 3: Sync FUT contracts
        # Fetch details for each FUT con_id, limited to front_n by expiry
        fut_contracts = [Contract(conId=cid) for cid in fut_con_ids]
        # Qualify in batches
        qualified_futs: list[Contract] = []
        for i in range(0, len(fut_contracts), BATCH_SIZE):
            batch = fut_contracts[i : i + BATCH_SIZE]
            qualified_futs.extend(ib.qualifyContracts(*batch))

        # Sort by expiry and limit to front_n
        fut_with_expiry: list[tuple[str, Contract]] = []
        for c in qualified_futs:
            expiry = (c.lastTradeDateOrContractMonth or "").strip()
            if c.conId and c.conId != 0:
                fut_with_expiry.append((expiry, c))
        fut_with_expiry.sort(key=lambda x: x[0])
        front_futs = fut_with_expiry[:front_n]

        front_fut_con_ids: set[int] = set()
        with Session(engine) as session:
            for _expiry, fut in front_futs:
                details = ib.reqContractDetails(fut)
                for detail in details:
                    cid = _upsert_contract(
                        session,
                        detail,
                        symbol,
                        "FUT",
                        exchange,
                        currency,
                        underlying_con_id=index_con_id,
                        now=now,
                    )
                    if cid:
                        front_fut_con_ids.add(cid)
                        counts["fut"] += 1

            # Deactivate FUT contracts not in this sync
            if front_fut_con_ids:
                from sqlalchemy import update

                session.execute(
                    update(ContractRef)
                    .where(
                        ContractRef.symbol == symbol,
                        ContractRef.sec_type == "FUT",
                        ContractRef.is_active.is_(True),
                        ContractRef.con_id.not_in(front_fut_con_ids),
                    )
                    .values(is_active=False, updated_at=now)
                )
            session.commit()

        logger.info("Synced %d FUT contracts for %s", counts["fut"], symbol)

        # Step 4: Store option chain metadata into option_chain_meta table
        # This is a fast DB-only operation — no IBKR qualification needed.
        # The full chain catalog lets the UI show all available options.
        # Actual contract qualification happens on-demand when a user selects one.
        from datetime import date

        from src.models import OptionChainMeta

        today = date.today()

        logger.info("Storing chain metadata for %s", symbol)

        meta_rows: list[dict] = []
        for info in chain_info:
            fut_cid = info["fut_con_id"]
            if fut_cid not in front_fut_con_ids:
                continue

            trading_class = info["trading_class"] or ""
            expirations = sorted(info["expirations"])
            strikes = sorted(info["strikes"])

            if not expirations or not strikes:
                continue

            # Filter out already-expired expirations
            valid_expirations = []
            for exp in expirations:
                try:
                    exp_date = date(int(exp[:4]), int(exp[4:6]), int(exp[6:8]))
                    if (exp_date - today).days >= 0:
                        valid_expirations.append(exp)
                except (ValueError, IndexError):
                    continue

            if not valid_expirations:
                continue

            logger.info(
                "FUT con_id=%d tc=%s: %d expirations, %d strikes [%.2f–%.2f]",
                fut_cid,
                trading_class,
                len(valid_expirations),
                len(strikes),
                min(strikes),
                max(strikes),
            )

            for exp in valid_expirations:
                for right_val in ("C", "P"):
                    for strike in strikes:
                        meta_rows.append(
                            {
                                "symbol": symbol,
                                "sec_type": "FOP",
                                "exchange": exchange,
                                "trading_class": trading_class,
                                "underlying_con_id": fut_cid,
                                "expiration": exp,
                                "strike": strike,
                                "right": right_val,
                                "synced_at": now,
                            }
                        )

        if meta_rows:
            meta_insert = insert(OptionChainMeta).values(meta_rows)
            meta_insert.on_conflict_do_update(
                constraint="uq_option_chain_meta_spec",
                set_={
                    "underlying_con_id": meta_insert.excluded.underlying_con_id,
                    "exchange": meta_insert.excluded.exchange,
                    "sec_type": meta_insert.excluded.sec_type,
                    "synced_at": meta_insert.excluded.synced_at,
                },
            )
            with Session(engine) as session:
                # Batch insert in chunks to avoid oversized SQL
                for i in range(0, len(meta_rows), 1000):
                    chunk = meta_rows[i : i + 1000]
                    chunk_insert = insert(OptionChainMeta).values(chunk)
                    chunk_upsert = chunk_insert.on_conflict_do_update(
                        constraint="uq_option_chain_meta_spec",
                        set_={
                            "underlying_con_id": chunk_insert.excluded.underlying_con_id,
                            "exchange": chunk_insert.excluded.exchange,
                            "sec_type": chunk_insert.excluded.sec_type,
                            "synced_at": chunk_insert.excluded.synced_at,
                        },
                    )
                    session.execute(chunk_upsert)
                session.commit()

        counts["chain_meta"] = len(meta_rows)
        logger.info("Stored %d option chain meta rows for %s", len(meta_rows), symbol)

        return {"symbol": symbol, **counts}
    finally:
        if owns_ib and ib.isConnected():
            ib.disconnect()
