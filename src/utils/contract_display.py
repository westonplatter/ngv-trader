"""Helpers for human-readable contract labels styled after IBKR TWS."""

from __future__ import annotations

import calendar

_MONTH_ABBR = {i: calendar.month_abbr[i] for i in range(1, 13)}


def _format_expiry_month_year(contract_expiry: str | None, contract_month: str | None) -> str | None:
    """Return ``Mon'YY`` from contract_expiry (YYYYMMDD) or contract_month (YYYY-MM)."""
    if contract_month and len(contract_month) >= 7:
        try:
            month = int(contract_month[5:7])
            year = contract_month[2:4]
            return f"{_MONTH_ABBR[month]}'{year}"
        except (ValueError, KeyError):
            pass

    if contract_expiry and len(contract_expiry) >= 6:
        try:
            month = int(contract_expiry[4:6])
            year = contract_expiry[2:4]
            return f"{_MONTH_ABBR[month]}'{year}"
        except (ValueError, KeyError):
            pass

    return None


def _format_expiry_day_month_year(contract_expiry: str | None) -> str | None:
    """Return ``MonDD'YY`` from contract_expiry (YYYYMMDD)."""
    if contract_expiry and len(contract_expiry) == 8:
        try:
            month = int(contract_expiry[4:6])
            day = int(contract_expiry[6:8])
            year = contract_expiry[2:4]
            return f"{_MONTH_ABBR[month]}{day}'{year}"
        except (ValueError, KeyError):
            pass
    return None


def _format_right(right: str | None) -> str | None:
    value = (right or "").strip().upper()
    if value in {"C", "CALL"}:
        return "CALL"
    if value in {"P", "PUT"}:
        return "PUT"
    return None


def contract_display_name(
    symbol: str | None,
    sec_type: str | None,
    *,
    right: str | None = None,
    strike: float | None = None,
    contract_expiry: str | None = None,
    contract_month: str | None = None,
    exchange: str | None = None,
    trading_class: str | None = None,
    include_exchange: bool = False,
) -> str:
    """Build a compact, IBKR TWS-style contract label.

    Examples (include_exchange=True):
    - STK:     ``AAPL @SMART``
    - FUT:     ``CL Dec'26 @NYMEX``
    - FOP/OPT: ``CL Feb27'26 62.75 PUT @NYMEX``
    - FOP with different trading_class: ``CL (LO4) Feb27'26 62.75 PUT @NYMEX``

    Examples (include_exchange=False, default):
    - STK:     ``AAPL``
    - FUT:     ``CL Dec'26``
    - FOP/OPT: ``CL (LO) May14'26 65 CALL``
    """
    sym = (symbol or "").strip().upper() or "UNKNOWN"
    stype = (sec_type or "").strip().upper()
    exch = (exchange or "").strip().upper() if include_exchange else ""
    tc = (trading_class or "").strip().upper()

    exch_suffix = f" @{exch}" if exch else ""

    if stype in {"STK", "IND"}:
        return f"{sym}{exch_suffix}"

    if stype == "FUT":
        expiry = _format_expiry_month_year(contract_expiry, contract_month)
        if expiry:
            return f"{sym} {expiry}{exch_suffix}"
        return f"{sym}{exch_suffix}"

    if stype in {"FOP", "OPT"}:
        parts = [sym]
        if tc and tc != sym:
            parts.append(f"({tc})")
        expiry = _format_expiry_day_month_year(contract_expiry)
        if expiry:
            parts.append(expiry)
        else:
            month_year = _format_expiry_month_year(contract_expiry, contract_month)
            if month_year:
                parts.append(month_year)
        if strike is not None:
            parts.append(f"{strike:g}")
        option_right = _format_right(right)
        if option_right:
            parts.append(option_right)
        if exch:
            parts.append(f"@{exch}")
        return " ".join(parts)

    # Fallback for other sec_types
    expiry = _format_expiry_month_year(contract_expiry, contract_month)
    if expiry:
        return f"{sym} {expiry}{exch_suffix}"
    return f"{sym}{exch_suffix}"
