"""Helpers for handling IBKR account identifiers safely."""


def mask_ibkr_account(account: str) -> str:
    """
    Mask an account string to avoid exposing the full identifier.

    Examples:
    - DU1234567 -> *******67
    - U9999999 -> ******99
    """
    normalized = account.strip()
    if not normalized:
        return "***"

    if len(normalized) <= 2:
        return "*" * len(normalized)

    hidden_count = len(normalized) - 2
    return f"{'*' * hidden_count}{normalized[-2:]}"
