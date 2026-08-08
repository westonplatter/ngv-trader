"""Custom SQLAlchemy column types.

``EncryptedString`` makes encryption-at-rest transparent at the model attribute:
the Python side reads and writes a plain string while the database stores Fernet
ciphertext. It deliberately takes no key argument — it calls the module-level
accessors in ``src.utils.crypto``, which is what lets the key rotate without
touching any model declaration.

Columns of this type cannot be indexed or filtered by value. Look rows up by a
plaintext column (a name) or by a foreign key instead.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from src.utils import crypto


class EncryptedString(TypeDecorator[str]):
    """Text column whose value is Fernet-encrypted on the way in and out.

    Stored as ``Text`` rather than ``LargeBinary``: Fernet output is already
    urlsafe-base64 ASCII, and text keeps `psql` inspection and snapshots
    readable.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return crypto.encrypt(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        return crypto.decrypt(str(value))
