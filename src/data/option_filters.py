"""Per-symbol option chain filtering defaults for FOP contract sync."""

OPTION_CHAIN_FILTERS: dict[str, dict] = {
    "GC": {
        "moneyness_gte": 95.0,
        "moneyness_lte": 105.0,
        "modulus_eq": 10.0,
    },
    "CL": {
        "moneyness_gte": 90.0,
        "moneyness_lte": 110.0,
        "modulus_eq": 1,
        "max_dte": 14,
    },
    "NQ": {
        "strike_gte": 27_000,
        "strike_lte": 30_000,
        "modulus_eq": 500.0,
    },
    "ES": {
        "moneyness_gte": 94.0,
        "moneyness_lte": 103.0,
        "modulus_eq": 5,
    },
    "AUD": {
        "strike_gte": 0.6,
        "strike_lte": 0.7,
        "modulus_eq": 0.01,
    },
    "GBP": {
        "moneyness_gte": 95.0,
        "moneyness_lte": 105.0,
        "modulus_eq": 0.005,
    },
    "default": {
        "moneyness_gte": 95.0,
        "moneyness_lte": 105.0,
        "modulus_eq": 5.0,
    },
}


def get_option_filter(symbol: str) -> dict:
    """Return the option filter config for a symbol, falling back to default."""
    return OPTION_CHAIN_FILTERS.get(symbol.upper(), OPTION_CHAIN_FILTERS["default"])


# Monthly (standard) trading classes per symbol.
# Everything else is treated as weekly/non-standard.
MONTHLY_TRADING_CLASSES: dict[str, set[str]] = {
    "CL": {"LO"},
    "ES": {"EW"},
    "NQ": {"NQ"},  # standard NQ options
    "GC": {"OG"},
    "default": set(),
}


def is_monthly_trading_class(symbol: str, trading_class: str) -> bool:
    """Return True if the trading class is a monthly (standard) series for the symbol."""
    monthly = MONTHLY_TRADING_CLASSES.get(symbol.upper(), MONTHLY_TRADING_CLASSES["default"])
    return trading_class in monthly
