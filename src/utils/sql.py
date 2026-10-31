"""Small helpers for building SQL expressions."""


def escape_like(value: str) -> str:
    """Escape LIKE metacharacters so %, _, and \\ are treated literally (use ``escape="\\"``)."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
