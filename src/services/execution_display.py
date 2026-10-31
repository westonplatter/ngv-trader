"""Display fields derived from an execution's raw IBKR payload.

The raw JSON carries the contract as TWS or FlexQuery sent it; these helpers
turn it into the display name and trade codes the trades and trade-group
endpoints show, filling gaps from the security master (``ContractRef``) and
from the local symbol itself.
"""

from __future__ import annotations

import re
from datetime import datetime

from src.models import ContractRef
from src.services.cl_contracts import infer_contract_month_from_local_symbol
from src.utils.contract_display import contract_display_name

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


def contract_display_from_raw(  # noqa: C901, PLR0912, PLR0915
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


def execution_ib_codes(raw: dict | None) -> str | None:
    """IBKR FlexQuery trade codes for an execution (the `notes` attribute).

    Semicolon-delimited codes like `A` (assigned), `Ep` (from expiration),
    `Ex` (exercise), `P` (partial), `WS` (wash sale). Lives only in the raw flex
    payload; TWS-sourced rows have no equivalent. Returns None when absent/empty.
    """
    if not raw:
        return None
    value = raw.get("notes")
    if value is None:
        return None
    text = str(value).strip()
    return text or None
