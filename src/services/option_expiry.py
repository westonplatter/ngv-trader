"""Option expiry and days-to-expiry from a raw IBKR expiry string."""

from __future__ import annotations

from datetime import date, datetime


def parse_raw_expiry_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    digits = value.replace("-", "")
    if len(digits) >= 8 and digits[:8].isdigit():
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except ValueError:
            return None
    return None


def option_expiry_and_dte(sec_type: str | None, raw_expiry: str | None) -> tuple[str | None, int | None]:
    """Expiry/DTE from raw values, for callers with no settled ``Position`` row.

    A position opened intraday has no FlexQuery snapshot, so its expiry has to
    come from elsewhere (the security master). Taking the two fields directly
    lets those callers reuse this rule instead of reimplementing it.
    """
    stype = (sec_type or "").strip().upper()
    expiry = parse_raw_expiry_date(raw_expiry)
    if expiry is None:
        return None, None

    option_expiry_date = expiry.isoformat() if stype in {"OPT", "FOP"} else None
    return option_expiry_date, (expiry - date.today()).days
