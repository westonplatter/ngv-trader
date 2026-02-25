"""Generic contract lookup service for any symbol/sec_type."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import ContractRef
from src.services.cl_contracts import (
    days_until_contract_expiry,
    display_contract_month,
    infer_contract_month_from_local_symbol,
)

DEFAULT_MIN_DAYS_TO_EXPIRY = 7


def find_contracts(
    session: Session,
    symbol: str,
    sec_type: str,
    is_active: bool = True,
    contract_month: str | None = None,
    min_days_to_expiry: int | None = None,
    strike: float | None = None,
    right: str | None = None,
) -> list[dict[str, Any]]:
    """Query contracts table with flexible filtering. Returns list of contract dicts."""
    stmt = (
        select(ContractRef)
        .where(
            ContractRef.symbol == symbol,
            ContractRef.sec_type == sec_type,
            ContractRef.is_active.is_(is_active),
        )
        .order_by(ContractRef.contract_expiry.asc())
    )

    if strike is not None:
        stmt = stmt.where(ContractRef.strike == strike)
    if right is not None:
        stmt = stmt.where(ContractRef.right == right.upper())
    if contract_month is not None:
        stmt = stmt.where(ContractRef.contract_month == contract_month)

    contracts = session.execute(stmt).scalars().all()

    results: list[dict[str, Any]] = []
    for c in contracts:
        dte = days_until_contract_expiry(c.contract_expiry or "")
        if min_days_to_expiry is not None and (dte is None or dte < min_days_to_expiry):
            continue
        results.append(_contract_to_dict(c, dte))

    return results


def select_contract(
    session: Session,
    symbol: str,
    sec_type: str,
    contract_month: str | None = None,
    min_days_to_expiry: int = DEFAULT_MIN_DAYS_TO_EXPIRY,
    strike: float | None = None,
    right: str | None = None,
    allow_fallback: bool = True,
) -> dict[str, Any]:
    """Select a single contract for trading.

    For FUT: selects by month (front-month fallback).
    For OPT/FOP: selects by month + strike + right.
    For STK: just finds the active contract for that symbol.

    Returns dict with contract details + metadata about what was
    requested vs available.
    """
    sec_upper = sec_type.upper()

    if sec_upper == "STK":
        return _select_stock(session, symbol)

    if sec_upper in ("OPT", "FOP"):
        return _select_option(
            session,
            symbol,
            sec_upper,
            contract_month=contract_month,
            min_days_to_expiry=min_days_to_expiry,
            strike=strike,
            right=right,
            allow_fallback=allow_fallback,
        )

    # FUT (and any other expiry-based type)
    return _select_future(
        session,
        symbol,
        sec_upper,
        contract_month=contract_month,
        min_days_to_expiry=min_days_to_expiry,
        allow_fallback=allow_fallback,
    )


def _contract_to_dict(c: ContractRef, dte: int | None) -> dict[str, Any]:
    inferred_contract_month = infer_contract_month_from_local_symbol(
        local_symbol=c.local_symbol,
        contract_expiry=c.contract_expiry,
        sec_type=c.sec_type,
    )
    contract_month = inferred_contract_month or c.contract_month
    return {
        "con_id": c.con_id,
        "symbol": c.symbol,
        "sec_type": c.sec_type,
        "exchange": c.exchange,
        "currency": c.currency,
        "local_symbol": c.local_symbol,
        "trading_class": c.trading_class,
        "contract_month": contract_month,
        "contract_expiry": c.contract_expiry,
        "multiplier": c.multiplier,
        "strike": c.strike,
        "right": c.right,
        "days_to_expiry": dte,
    }


def _load_candidates(
    session: Session,
    symbol: str,
    sec_type: str,
    min_days_to_expiry: int,
    strike: float | None = None,
    right: str | None = None,
) -> list[tuple[ContractRef, int]]:
    """Load active contracts filtered by DTE, optionally by strike/right."""
    stmt = (
        select(ContractRef)
        .where(
            ContractRef.symbol == symbol,
            ContractRef.sec_type == sec_type,
            ContractRef.is_active.is_(True),
        )
        .order_by(ContractRef.contract_expiry.asc())
    )
    if strike is not None:
        stmt = stmt.where(ContractRef.strike == strike)
    if right is not None:
        stmt = stmt.where(ContractRef.right == right.upper())

    contracts = session.execute(stmt).scalars().all()
    candidates: list[tuple[ContractRef, int]] = []
    for c in contracts:
        dte = days_until_contract_expiry(c.contract_expiry or "")
        if dte is not None and dte >= min_days_to_expiry:
            candidates.append((c, dte))
    return candidates


def _group_by_month(
    candidates: list[tuple[ContractRef, int]],
) -> dict[str, tuple[ContractRef, int]]:
    """Group candidates by contract_month, keeping first (earliest expiry) per month."""
    by_month: dict[str, tuple[ContractRef, int]] = {}
    for c, dte in candidates:
        month = c.contract_month
        if month and month not in by_month:
            by_month[month] = (c, dte)
    return by_month


def _pick_month(
    contracts_by_month: dict[str, tuple[ContractRef, int]],
    requested_contract_month: str | None,
    allow_fallback: bool,
    label: str,
) -> tuple[ContractRef, int, str | None, bool, list[str]]:
    """Pick a contract month. Returns (contract, dte, requested_month, requested_available, available_months)."""
    available_months = list(contracts_by_month.keys())

    requested_available = requested_contract_month in contracts_by_month if requested_contract_month is not None else True

    if requested_contract_month and requested_available:
        selected_month = requested_contract_month
    elif requested_contract_month and not requested_available:
        if not allow_fallback:
            available_text = ", ".join(display_contract_month(m) for m in available_months)
            raise ValueError(
                f"{display_contract_month(requested_contract_month)} {label} contract is not currently available. "
                f"Available contract months: {available_text}."
            )
        selected_month = available_months[0]
    else:
        selected_month = available_months[0]

    selected, selected_dte = contracts_by_month[selected_month]
    return (
        selected,
        selected_dte,
        requested_contract_month,
        requested_available,
        available_months,
    )


def _build_result(
    selected: ContractRef,
    selected_dte: int,
    requested_contract_month: str | None,
    requested_available: bool,
    available_months: list[str],
) -> dict[str, Any]:
    result = _contract_to_dict(selected, selected_dte)
    result["requested_contract_month"] = requested_contract_month
    result["requested_available"] = requested_available
    result["available_contract_months"] = available_months
    return result


def _select_stock(session: Session, symbol: str) -> dict[str, Any]:
    stmt = (
        select(ContractRef)
        .where(
            ContractRef.symbol == symbol,
            ContractRef.sec_type == "STK",
            ContractRef.is_active.is_(True),
        )
        .limit(1)
    )
    contract = session.execute(stmt).scalars().first()
    if contract is None:
        raise ValueError(f"No active STK contract for {symbol} in the database. " "Run a contracts.sync job first (enqueue_contracts_sync_job).")
    result = _contract_to_dict(contract, None)
    result["requested_contract_month"] = None
    result["requested_available"] = True
    result["available_contract_months"] = []
    return result


def _select_future(
    session: Session,
    symbol: str,
    sec_type: str,
    contract_month: str | None,
    min_days_to_expiry: int,
    allow_fallback: bool,
) -> dict[str, Any]:
    candidates = _load_candidates(session, symbol, sec_type, min_days_to_expiry)
    if not candidates:
        raise ValueError(
            f"No active {symbol} {sec_type} contracts in the database outside the near-expiry safety window "
            f"(min_days_to_expiry={min_days_to_expiry}). "
            "Run a contracts.sync job first (enqueue_contracts_sync_job)."
        )

    contracts_by_month = _group_by_month(candidates)
    if not contracts_by_month:
        raise ValueError(f"No {symbol} {sec_type} contracts with valid contract_month data.")

    selected, dte, req_month, req_available, avail_months = _pick_month(
        contracts_by_month,
        contract_month,
        allow_fallback,
        f"{symbol} {sec_type}",
    )
    return _build_result(selected, dte, req_month, req_available, avail_months)


def _select_option(
    session: Session,
    symbol: str,
    sec_type: str,
    contract_month: str | None,
    min_days_to_expiry: int,
    strike: float | None,
    right: str | None,
    allow_fallback: bool,
) -> dict[str, Any]:
    # If strike/right provided, filter directly
    candidates = _load_candidates(
        session,
        symbol,
        sec_type,
        min_days_to_expiry,
        strike=strike,
        right=right,
    )

    if not candidates and strike is not None:
        # No exact strike match — find available strikes to report
        all_candidates = _load_candidates(session, symbol, sec_type, min_days_to_expiry, right=right)
        available_strikes = sorted({c.strike for c, _ in all_candidates if c.strike is not None})
        strikes_text = ", ".join(str(s) for s in available_strikes[:20])
        raise ValueError(f"No active {symbol} {sec_type} contract with strike={strike}. " f"Available strikes: {strikes_text or 'none (run contracts.sync)'}.")

    if not candidates:
        raise ValueError(
            f"No active {symbol} {sec_type} contracts in the database outside the near-expiry safety window "
            f"(min_days_to_expiry={min_days_to_expiry}). "
            "Run a contracts.sync job first (enqueue_contracts_sync_job)."
        )

    contracts_by_month = _group_by_month(candidates)
    if not contracts_by_month:
        raise ValueError(f"No {symbol} {sec_type} contracts with valid contract_month data.")

    selected, dte, req_month, req_available, avail_months = _pick_month(
        contracts_by_month,
        contract_month,
        allow_fallback,
        f"{symbol} {sec_type}",
    )
    return _build_result(selected, dte, req_month, req_available, avail_months)
