"""Futures exchange mappings shared across the codebase."""

FUTURES_EXCHANGE_MAP: dict[str, str] = {
    "CL": "NYMEX",
    "MCL": "NYMEX",
    "NG": "NYMEX",
    "HO": "NYMEX",
    "RB": "NYMEX",
    "ES": "CME",
    "MES": "CME",
    "NQ": "CME",
    "MNQ": "CME",
    "RTY": "CME",
    "M2K": "CME",
    "YM": "CBOT",
    "MYM": "CBOT",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
    "ZT": "CBOT",
    "ZC": "CBOT",
    "ZS": "CBOT",
    "ZW": "CBOT",
    "GC": "COMEX",
    "MGC": "COMEX",
    "SI": "COMEX",
    "SIL": "COMEX",
    "HG": "COMEX",
}


def resolve_exchange(symbol: str, sec_type: str) -> str:
    """Resolve exchange for a symbol. Returns exchange or raises if unknown futures symbol."""
    if sec_type in ("FUT", "FOP"):
        normalized_symbol = symbol[1:] if symbol.startswith("/") else symbol
        exchange = FUTURES_EXCHANGE_MAP.get(normalized_symbol)
        if exchange is None:
            known = ", ".join(sorted(FUTURES_EXCHANGE_MAP.keys()))
            raise ValueError(f"Unknown exchange for futures symbol '{symbol}'. " f"Known symbols: {known}. " "Please tell me which exchange this trades on.")
        return exchange
    if sec_type == "OPT":
        return "SMART"
    return "SMART"
