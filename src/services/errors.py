"""Errors services raise for bad input, mapped to HTTP status codes by the API.

Services never import FastAPI. They raise a ``ServiceError`` (or a subclass) with
a readable message; ``src/api/main.py`` turns it into ``{"detail": message}`` with
the class's ``status_code``. Routers that need another status (409 on a rename
collision, say) still raise ``HTTPException`` themselves.
"""


class ServiceError(ValueError):
    """Input a service cannot act on. The API answers 400."""

    status_code = 400


class NotFoundError(ServiceError):
    """Input that names an item which does not exist. The API answers 404."""

    status_code = 404
