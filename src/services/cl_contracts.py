"""Helpers for qualifying CL futures contracts via IBKR."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from ib_async import IB, Contract, Future

DEFAULT_CL_MIN_DAYS_TO_EXPIRY = 7
_FUTURES_MONTH_CODE_TO_MONTH = {
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
_FUTURES_LOCAL_SYMBOL_PATTERN = re.compile(r"([FGHJKMNQUVXZ])(\d{1,2})$")


@dataclass(frozen=True)
class QualifiedContract:
    con_id: int
    symbol: str
    sec_type: str
    exchange: str
    currency: str
    local_symbol: str | None
    trading_class: str | None
    contract_month: str | None
    contract_expiry: str | None


def parse_contract_expiry(last_trade_or_month: str) -> dt.date | None:
    value = (last_trade_or_month or "").strip()
    if len(value) >= 8 and value[:8].isdigit():
        try:
            return dt.datetime.strptime(value[:8], "%Y%m%d").date()
        except ValueError:
            return None
    if len(value) >= 6 and value[:6].isdigit():
        try:
            year = int(value[:4])
            month = int(value[4:6])
            if month == 12:
                next_month = dt.date(year + 1, 1, 1)
            else:
                next_month = dt.date(year, month + 1, 1)
            return next_month - dt.timedelta(days=1)
        except ValueError:
            return None
    return None


def days_until_contract_expiry(last_trade_or_month: str, today: dt.date | None = None) -> int | None:
    expiry = parse_contract_expiry(last_trade_or_month)
    if expiry is None:
        return None
    comparison_day = today or dt.date.today()
    return (expiry - comparison_day).days


def contract_days_to_expiry(contract: Contract, today: dt.date | None = None) -> int | None:
    return days_until_contract_expiry(contract.lastTradeDateOrContractMonth, today=today)


def format_contract_month(contract: Contract) -> str | None:
    raw_value = (contract.lastTradeDateOrContractMonth or "").strip()
    inferred = infer_contract_month_from_local_symbol(
        local_symbol=(contract.localSymbol or None),
        contract_expiry=(raw_value or None),
        sec_type=(contract.secType or None),
    )
    if inferred is not None:
        return inferred
    if len(raw_value) >= 6 and raw_value[:6].isdigit():
        return f"{raw_value[:4]}-{raw_value[4:6]}"

    expiry = parse_contract_expiry(raw_value)
    if expiry is not None:
        return expiry.strftime("%Y-%m")
    return None


def select_front_month_contract(ib: IB, min_days_to_expiry: int = DEFAULT_CL_MIN_DAYS_TO_EXPIRY) -> Contract:
    if min_days_to_expiry < 0:
        raise ValueError("min_days_to_expiry must be >= 0")

    contract_details = ib.reqContractDetails(Future("CL", exchange="NYMEX", currency="USD"))
    if not contract_details:
        raise RuntimeError("No CL futures contract details returned from IBKR")

    candidates: list[tuple[dt.date, Contract]] = []
    non_expired: list[tuple[dt.date, Contract]] = []
    for detail in contract_details:
        contract = detail.contract
        if contract is None:
            continue
        expiry = parse_contract_expiry(contract.lastTradeDateOrContractMonth)
        days_to_expiry = contract_days_to_expiry(contract)
        if contract.secType != "FUT" or expiry is None or days_to_expiry is None or days_to_expiry < 0:
            continue
        non_expired.append((expiry, contract))
        if days_to_expiry < min_days_to_expiry:
            continue
        candidates.append((expiry, contract))

    if not candidates:
        if non_expired:
            nearest_expiry, nearest_contract = min(non_expired, key=lambda item: item[0])
            nearest_days = contract_days_to_expiry(nearest_contract)
            raise RuntimeError(
                "No CL futures contracts found outside the near-expiry safety window "
                f"(min_days_to_expiry={min_days_to_expiry}). "
                f"Nearest non-expired contract: {nearest_contract.localSymbol or nearest_contract.symbol} "
                f"expiring {nearest_expiry.isoformat()} ({nearest_days} days)."
            )
        raise RuntimeError("No non-expired CL futures contracts found")

    candidates.sort(key=lambda item: item[0])
    front_month_contract = candidates[0][1]
    qualified_contracts = ib.qualifyContracts(front_month_contract)
    if len(qualified_contracts) != 1:
        raise RuntimeError(f"Expected exactly one qualified front-month contract, got {len(qualified_contracts)}")
    return qualified_contracts[0]


def format_contract_month_from_expiry(contract_expiry: str | None) -> str | None:
    """Derive YYYY-MM contract month from a raw IB expiry string (no IB objects needed)."""
    raw = (contract_expiry or "").strip()
    if len(raw) >= 6 and raw[:6].isdigit():
        return f"{raw[:4]}-{raw[4:6]}"
    expiry = parse_contract_expiry(raw)
    if expiry is not None:
        return expiry.strftime("%Y-%m")
    return None


def _infer_year_from_code(year_code: str, fallback_year: int | None) -> int:
    if len(year_code) == 2:
        return 2000 + int(year_code)

    digit = int(year_code)
    if fallback_year is None:
        current_year = dt.date.today().year
        base = (current_year // 10) * 10 + digit
        if base < current_year:
            base += 10
        return base

    decade = (fallback_year // 10) * 10
    candidates = [decade - 10 + digit, decade + digit, decade + 10 + digit]
    return min(candidates, key=lambda candidate: abs(candidate - fallback_year))


def infer_contract_month_from_local_symbol(
    local_symbol: str | None,
    contract_expiry: str | None,
    sec_type: str | None,
) -> str | None:
    """Infer contract month from a futures local symbol like CLJ6/CLJ26."""
    if (sec_type or "").upper() != "FUT":
        return None

    raw_local_symbol = (local_symbol or "").strip().upper()
    if not raw_local_symbol:
        return None

    match = _FUTURES_LOCAL_SYMBOL_PATTERN.search(raw_local_symbol)
    if match is None:
        return None

    month_code = match.group(1)
    year_code = match.group(2)
    month = _FUTURES_MONTH_CODE_TO_MONTH.get(month_code)
    if month is None:
        return None

    fallback_year = None
    expiry_date = parse_contract_expiry(contract_expiry or "")
    if expiry_date is not None:
        fallback_year = expiry_date.year
    elif contract_expiry and len(contract_expiry) >= 4 and contract_expiry[:4].isdigit():
        fallback_year = int(contract_expiry[:4])

    year = _infer_year_from_code(year_code, fallback_year)
    return f"{year:04d}-{month:02d}"


def normalize_contract_month_input(contract_month: str | None) -> str | None:
    """Parse user-provided contract month into YYYY-MM format.

    Accepts: YYYY-MM, YYYYMM, "March 2026", "Mar 2026", etc.
    Returns None for empty/None input.
    """
    if contract_month is None:
        return None

    raw = contract_month.strip().replace("/", "-").replace(",", " ")
    if not raw:
        return None

    compact = " ".join(raw.split())
    if len(compact) == 7 and compact[4] == "-" and compact[:4].isdigit() and compact[5:7].isdigit():
        year = int(compact[:4])
        month = int(compact[5:7])
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        raise ValueError("contract_month must use a valid month.")

    if len(compact) == 6 and compact.isdigit():
        year = int(compact[:4])
        month = int(compact[4:6])
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
        raise ValueError("contract_month must use a valid month.")

    for fmt in ("%B %Y", "%b %Y"):
        try:
            parsed = dt.datetime.strptime(compact.title(), fmt)
            return parsed.strftime("%Y-%m")
        except ValueError:
            continue

    raise ValueError("contract_month must be YYYY-MM, YYYYMM, or a month name like 'March 2026'.")


def display_contract_month(contract_month: str) -> str:
    """Format YYYY-MM as 'March 2026'."""
    try:
        parsed = dt.datetime.strptime(contract_month, "%Y-%m")
    except ValueError:
        return contract_month
    return parsed.strftime("%B %Y")


def to_qualified_contract(contract: Contract) -> QualifiedContract:
    raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip()
    return QualifiedContract(
        con_id=contract.conId,
        symbol=contract.symbol or "CL",
        sec_type=contract.secType or "FUT",
        exchange=contract.exchange or "NYMEX",
        currency=contract.currency or "USD",
        local_symbol=contract.localSymbol,
        trading_class=contract.tradingClass,
        contract_month=format_contract_month(contract),
        contract_expiry=raw_expiry or None,
    )
