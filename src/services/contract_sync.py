"""Sync contract details from IBKR into the contracts table."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ib_async import IB, Contract, Future
from ib_async import Index as IbIndex
from sqlalchemy import Engine, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import (
    PRODUCT_DISCOVERY_ACTIVE,
    PRODUCT_DISCOVERY_NEEDS_DISAMBIGUATION,
    PRODUCT_DISCOVERY_UNKNOWN_SYMBOL,
    ActivatedProduct,
    ContractRef,
)
from src.services.cl_contracts import (
    format_contract_month_from_expiry,
    infer_contract_month_from_local_symbol,
    parse_contract_expiry,
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
                    # IBKR ContractDetails.priceMagnifier (1 for most products,
                    # 100 for cents-quoted ones like grains). Authoritative source.
                    "price_magnifier": int(getattr(detail, "priceMagnifier", None) or 1),
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
        # IBKR ContractDetails.priceMagnifier (1 for most products, 100 for
        # cents-quoted ones like grains). Authoritative source.
        "price_magnifier": int(getattr(detail, "priceMagnifier", None) or 1),
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


# ---------------------------------------------------------------------------
# Activated products: discover exchange/metadata from IBKR by symbol alone,
# then maintain the next N calendar months of FUT contracts in the security
# master.
# ---------------------------------------------------------------------------


@dataclass
class ProductDiscovery:
    """Result of discovering a futures product from IBKR by symbol alone."""

    symbol: str
    sec_type: str
    currency: str
    exchanges: list[str] = field(default_factory=list)
    exchange: str | None = None
    valid_exchanges: str | None = None
    multiplier: str | None = None
    trading_class: str | None = None
    long_name: str | None = None
    min_tick: float | None = None
    details: list[Any] = field(default_factory=list)
    status: str = PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
    error: str | None = None


def discover_product_metadata(
    ib: IB,
    symbol: str,
    sec_type: str = "FUT",
    currency: str = "USD",
) -> ProductDiscovery:
    """Discover a futures product's exchange and metadata from IBKR.

    Builds a ``Future`` spec with no exchange and calls ``reqContractDetails``,
    which IBKR treats as a wildcard across venues. The returned contract details
    carry the listing exchange plus contract metadata, and they double as the
    list of contracts to upsert into the security master.

    Resolution rules:
      - exactly one distinct exchange -> ``active`` with that exchange
      - more than one distinct exchange -> ``needs_disambiguation`` (no guess)
      - zero results -> ``unknown_symbol``
    """
    sec_type = (sec_type or "FUT").upper()
    spec = Future(symbol, currency=currency) if sec_type == "FUT" else Contract(symbol=symbol, secType=sec_type, currency=currency)

    discovery = ProductDiscovery(symbol=symbol, sec_type=sec_type, currency=currency)

    try:
        details = ib.reqContractDetails(spec)
    except Exception as exc:  # noqa: BLE001
        discovery.status = PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
        discovery.error = f"reqContractDetails failed for {symbol}: {exc}"
        return discovery

    details = [d for d in (details or []) if getattr(d, "contract", None) is not None and d.contract.conId]
    discovery.details = details

    if not details:
        discovery.status = PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
        discovery.error = f"IBKR returned no contracts for symbol '{symbol}' (sec_type={sec_type})."
        return discovery

    # Collect distinct listing exchanges across the returned contracts.
    exchanges = sorted({(d.contract.exchange or "").strip() for d in details if (d.contract.exchange or "").strip()})
    discovery.exchanges = exchanges

    # Metadata from the first detail (shared across a product's contracts).
    first = details[0]
    first_contract = first.contract
    discovery.multiplier = (first_contract.multiplier or None) or None
    discovery.trading_class = (first_contract.tradingClass or None) or None
    discovery.long_name = (getattr(first, "longName", None) or None) or None
    valid_exchanges = (getattr(first, "validExchanges", None) or "").strip() or None
    discovery.valid_exchanges = valid_exchanges
    min_tick_raw = getattr(first, "minTick", None)
    try:
        discovery.min_tick = float(min_tick_raw) if min_tick_raw not in (None, 0, 0.0) else None
    except (TypeError, ValueError):
        discovery.min_tick = None

    if len(exchanges) == 1:
        discovery.exchange = exchanges[0]
        discovery.status = PRODUCT_DISCOVERY_ACTIVE
    elif len(exchanges) > 1:
        discovery.status = PRODUCT_DISCOVERY_NEEDS_DISAMBIGUATION
        discovery.error = f"Symbol '{symbol}' resolves to multiple exchanges: {', '.join(exchanges)}. Set exchange explicitly."
    else:
        discovery.status = PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
        discovery.error = f"IBKR returned contracts for '{symbol}' but none carried an exchange."

    return discovery


def _add_months(start: dt.date, months: int) -> dt.date:
    """Return ``start`` advanced by ``months`` calendar months (clamped day)."""
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    if month == 12:
        next_month_first = dt.date(year + 1, 1, 1)
    else:
        next_month_first = dt.date(year, month + 1, 1)
    last_day = (next_month_first - dt.timedelta(days=1)).day
    return dt.date(year, month, min(start.day, last_day))


def _is_within_window(contract_expiry: str | None, today: dt.date, cutoff: dt.date) -> bool:
    """True if the contract expires on or after today and on or before cutoff."""
    if not contract_expiry:
        return False
    expiry = parse_contract_expiry(contract_expiry)
    if expiry is None:
        return False
    return today <= expiry <= cutoff


def _sync_one_product(
    session: Session,
    ib: IB,
    product: ActivatedProduct,
    now: datetime,
) -> dict:
    """Discover (if needed) and sync the next-N-months FUT contracts for one product."""
    symbol = product.symbol
    sec_type = (product.sec_type or "FUT").upper()
    currency = product.currency or "USD"
    months_ahead = product.months_ahead or 12

    discovery = discover_product_metadata(ib, symbol, sec_type, currency)

    # Persist discovered metadata regardless of outcome.
    product.valid_exchanges = discovery.valid_exchanges or product.valid_exchanges
    product.multiplier = discovery.multiplier or product.multiplier
    product.trading_class = discovery.trading_class or product.trading_class
    product.long_name = discovery.long_name or product.long_name
    product.min_tick = discovery.min_tick if discovery.min_tick is not None else product.min_tick
    product.updated_at = now

    # Choose the exchange: an operator-set value wins; otherwise use discovery.
    exchange = (product.exchange or "").strip() or discovery.exchange

    if discovery.status != PRODUCT_DISCOVERY_ACTIVE and not exchange:
        product.discovery_status = discovery.status
        product.last_error = discovery.error
        return {
            "symbol": symbol,
            "status": discovery.status,
            "error": discovery.error,
            "upserted": 0,
            "deactivated": 0,
        }

    product.exchange = exchange

    today = now.date()
    cutoff = _add_months(today, months_ahead)

    synced_con_ids: set[int] = set()
    upserted = 0
    for detail in discovery.details:
        contract = detail.contract
        if (contract.exchange or "").strip() != exchange:
            # Skip contracts from a different venue than the chosen exchange.
            continue
        if not _is_within_window(contract.lastTradeDateOrContractMonth, today, cutoff):
            continue
        cid = _upsert_contract(
            session,
            detail,
            symbol,
            sec_type,
            exchange,
            currency,
            underlying_con_id=None,
            now=now,
        )
        if cid:
            synced_con_ids.add(cid)
            upserted += 1

    # Deactivate this product's in-DB contracts that fell outside the window.
    deactivated = 0
    if synced_con_ids:
        result = session.execute(
            update(ContractRef)
            .where(
                ContractRef.symbol == symbol,
                ContractRef.sec_type == sec_type,
                ContractRef.is_active.is_(True),
                ContractRef.con_id.not_in(synced_con_ids),
            )
            .values(is_active=False, updated_at=now)
        )
        deactivated = result.rowcount or 0

    product.discovery_status = PRODUCT_DISCOVERY_ACTIVE
    product.last_error = None
    product.last_synced_at = now

    logger.info(
        "Activated product %s synced on %s: upserted=%d deactivated=%d window=%s..%s",
        symbol,
        exchange,
        upserted,
        deactivated,
        today.isoformat(),
        cutoff.isoformat(),
    )

    return {
        "symbol": symbol,
        "status": PRODUCT_DISCOVERY_ACTIVE,
        "exchange": exchange,
        "upserted": upserted,
        "deactivated": deactivated,
    }


def sync_activated_products_with_ib(
    engine: Engine,
    *,
    ib: IB,
    symbols: list[str] | None = None,
) -> dict:
    """Discover + sync the next-N-calendar-month FUT contracts for activated products.

    Reads active rows from ``activated_products`` (optionally filtered to
    ``symbols``), discovers each product's exchange/metadata from IBKR when
    missing, upserts the in-window contracts into the ``contracts`` security
    master, and deactivates out-of-window rows. The caller owns the IB session.
    """
    now = _now_utc()
    stmt = select(ActivatedProduct).where(ActivatedProduct.is_active.is_(True)).order_by(ActivatedProduct.symbol.asc())
    if symbols:
        wanted = [s.strip().upper() for s in symbols if s.strip()]
        stmt = stmt.where(ActivatedProduct.symbol.in_(wanted))

    results: list[dict] = []
    with Session(engine) as session:
        products = session.execute(stmt).scalars().all()
        for product in products:
            try:
                results.append(_sync_one_product(session, ib, product, now))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Activated product sync failed for %s", product.symbol)
                product.discovery_status = PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
                product.last_error = str(exc)
                product.updated_at = now
                results.append({"symbol": product.symbol, "status": "error", "error": str(exc)})
        session.commit()

    return {
        "products": results,
        "products_count": len(results),
        "active_count": sum(1 for r in results if r.get("status") == PRODUCT_DISCOVERY_ACTIVE),
        "total_upserted": sum(int(r.get("upserted", 0)) for r in results),
    }


def sync_activated_products(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 20.0,
    symbols: list[str] | None = None,
) -> dict:
    """Connect to IBKR and sync activated products (standalone entrypoint)."""
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                f"Timed out connecting to TWS/Gateway for activated-products sync " f"(host={host}, port={port}, client_id={client_id})."
            ) from exc
        return sync_activated_products_with_ib(engine=engine, ib=ib, symbols=symbols)
    finally:
        if ib.isConnected():
            ib.disconnect()
