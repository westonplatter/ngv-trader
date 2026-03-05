"""Helpers for handling IBKR account identifiers safely."""


def mask_ibkr_account(account: str) -> str:
    """
    Mask an account string to avoid exposing the full identifier.

    Examples:
    - DU1234567 -> ******567
    - U9999999 -> *****999
    """
    normalized = account.strip()
    if not normalized:
        return "***"

    visible_digits = 3

    if len(normalized) <= visible_digits:
        return "*" * len(normalized)

    hidden_count = len(normalized) - visible_digits
    return f"{'*' * hidden_count}{normalized[-visible_digits:]}"
