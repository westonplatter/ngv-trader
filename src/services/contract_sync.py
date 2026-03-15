"""Sync contract details from IBKR into the contracts table."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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
    front_n: int = 6,
    option_filter: dict | None = None,
    connect_timeout_seconds: float = 20.0,
    ib: IB | None = None,
) -> dict:
    """3-step IND → FUT → FOP contract discovery and sync.

    1. Qualify the Index contract
    2. Discover the option chain via reqSecDefOptParams
    3. Sync FUT contracts (limited to front_n)
    4. Sync FOP contracts (all strikes, filtered by DTE range)

    option_filter keys (all optional):
      - min_dte: minimum days to expiry (default 0)
      - max_dte: maximum days to expiry (default None = no limit)

    Price fetching (market_data.futures_options) still uses narrow strike/moneyness
    filters. If a user selects a contract without prices, a targeted snapshot job
    can be kicked off.
    """
    filt = option_filter or {}
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

        logger.info("Syncing ALL FOP contracts for %s (no strike filtering)", symbol)

        # Step 4: Sync ALL FOP contracts for each front FUT underlying
        # Contract metadata is synced unfiltered so the UI can show the full chain.
        # Price fetching (market_data.futures_options) still uses narrow filters.
        # Load existing FOP coverage from DB to skip redundant IBKR calls
        from datetime import date

        from sqlalchemy import select

        # Build a set of (underlying_con_id, trading_class, expiry, right, strike)
        # for existing contracts so we can skip individual specs we already have
        existing_con_ids: set[int] = set()
        existing_specs: set[tuple[int, str, str, str, float]] = set()
        with Session(engine) as session:
            spec_q = select(
                ContractRef.con_id,
                ContractRef.underlying_con_id,
                ContractRef.trading_class,
                ContractRef.contract_expiry,
                ContractRef.right,
                ContractRef.strike,
            ).where(
                ContractRef.symbol == symbol,
                ContractRef.sec_type == "FOP",
                ContractRef.is_active.is_(True),
            )
            for row in session.execute(spec_q):
                existing_con_ids.add(row.con_id)
                if row.underlying_con_id and row.contract_expiry and row.right and row.strike:
                    existing_specs.add(
                        (
                            row.underlying_con_id,
                            row.trading_class or "",
                            row.contract_expiry,
                            row.right,
                            float(row.strike),
                        )
                    )

        logger.info(
            "Existing FOP coverage: %d contracts (%d unique specs) in DB",
            len(existing_con_ids),
            len(existing_specs),
        )

        counts["fop_skipped"] = 0

        # Phase 1: Build FOP Contract specs to qualify
        # Each entry: (Contract spec, fut_con_id for underlying)
        # Filter expirations by min_dte / max_dte from option_filter if provided
        fop_specs: list[tuple[Contract, int]] = []
        today = date.today()
        min_dte = filt.get("min_dte", 0) if filt else 0
        max_dte = filt.get("max_dte") if filt else None

        logger.info(
            "FOP DTE filter: min_dte=%s, max_dte=%s",
            min_dte,
            max_dte if max_dte is not None else "none",
        )

        for info in chain_info:
            fut_cid = info["fut_con_id"]
            if fut_cid not in front_fut_con_ids:
                continue

            trading_class = info["trading_class"] or ""
            expirations = sorted(info["expirations"])
            strikes = sorted(info["strikes"])

            if not expirations or not strikes:
                continue

            # Filter expirations by DTE range
            valid_expirations = []
            for exp in expirations:
                try:
                    exp_date = date(int(exp[:4]), int(exp[4:6]), int(exp[6:8]))
                    dte_val = (exp_date - today).days
                    if dte_val < min_dte:
                        continue
                    if max_dte is not None and dte_val > max_dte:
                        continue
                    valid_expirations.append(exp)
                except (ValueError, IndexError):
                    continue

            if not valid_expirations:
                continue

            lo = min(strikes)
            hi = max(strikes)

            logger.info(
                "FUT con_id=%d tc=%s: %d expirations, %d strikes [%.2f–%.2f]",
                fut_cid,
                trading_class,
                len(valid_expirations),
                len(strikes),
                lo,
                hi,
            )

            skipped_existing = 0
            for expiry in valid_expirations:
                for right_val in ("C", "P"):
                    for strike in strikes:
                        # Skip if we already have this exact contract in the DB
                        if (fut_cid, trading_class, expiry, right_val, strike) in existing_specs:
                            skipped_existing += 1
                            continue
                        spec = Contract(
                            symbol=symbol,
                            secType="FOP",
                            exchange=exchange,
                            currency=currency,
                            lastTradeDateOrContractMonth=expiry,
                            tradingClass=trading_class,
                            right=right_val,
                            strike=strike,
                        )
                        fop_specs.append((spec, fut_cid))
            if skipped_existing:
                logger.info(
                    "FUT con_id=%d tc=%s: skipped %d specs already in DB",
                    fut_cid,
                    trading_class,
                    skipped_existing,
                )

        logger.info("Phase 1: built %d FOP specs to qualify", len(fop_specs))

        if not fop_specs:
            return {"symbol": symbol, **counts}

        # Phase 2: Batch qualify all FOP specs
        all_specs = [spec for spec, _ in fop_specs]
        fut_cid_by_idx = {i: fut_cid for i, (_, fut_cid) in enumerate(fop_specs)}

        qualified_fops: list[tuple[Contract, int]] = []
        for i in range(0, len(all_specs), BATCH_SIZE):
            batch = all_specs[i : i + BATCH_SIZE]
            results = ib.qualifyContracts(*batch)
            for j, contract in enumerate(results):
                if contract.conId and contract.conId != 0:
                    qualified_fops.append((contract, fut_cid_by_idx[i + j]))

        logger.info("Phase 2: qualified %d/%d FOP contracts", len(qualified_fops), len(all_specs))

        # Phase 3: Batch upsert, skipping contracts already in DB
        new_fop_count = 0
        skipped_count = 0
        with Session(engine) as session:
            for contract, fut_cid in qualified_fops:
                if contract.conId in existing_con_ids:
                    skipped_count += 1
                    continue

                raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
                contract_month = infer_contract_month_from_local_symbol(
                    local_symbol=contract.localSymbol or None,
                    contract_expiry=raw_expiry,
                    sec_type="FOP",
                ) or format_contract_month_from_expiry(raw_expiry)

                values = {
                    "con_id": contract.conId,
                    "symbol": contract.symbol or symbol,
                    "sec_type": "FOP",
                    "exchange": contract.exchange or exchange,
                    "currency": contract.currency or currency,
                    "local_symbol": contract.localSymbol or None,
                    "trading_class": contract.tradingClass or None,
                    "contract_month": contract_month,
                    "contract_expiry": raw_expiry,
                    "multiplier": contract.multiplier or None,
                    "strike": contract.strike if contract.strike and contract.strike != 0.0 else None,
                    "right": contract.right if contract.right and contract.right != "?" else None,
                    "primary_exchange": contract.primaryExchange or None,
                    "underlying_con_id": fut_cid,
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
                existing_con_ids.add(contract.conId)
                new_fop_count += 1

            session.commit()

        counts["fop"] = new_fop_count
        counts["fop_skipped"] = skipped_count

        logger.info(
            "Phase 3: upserted %d new FOPs, skipped %d (already in DB)",
            new_fop_count,
            skipped_count,
        )

        return {"symbol": symbol, **counts}
    finally:
        if owns_ib and ib.isConnected():
            ib.disconnect()
