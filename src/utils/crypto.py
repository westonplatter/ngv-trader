"""Fernet encryption helpers for secrets stored at rest in Postgres.

The key set lives in ``FLEX_TOKEN_ENCRYPTION_KEY`` as a comma-separated list of
urlsafe-base64 Fernet keys. The first key encrypts; every key is tried on
decrypt, which is what makes rotation possible without downtime:

    1. prepend a new key to ``FLEX_TOKEN_ENCRYPTION_KEY``
    2. run ``scripts/manage_flex_tokens.py rotate-key``
    3. drop the old key

Resolution is lazy — the key is read on first encrypt/decrypt, never at import,
so ``alembic``, ``scripts/check.py``, and the API all start on a machine that
has no key configured.

Nothing here ever puts key or plaintext material into an exception message.
"""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from src.utils.env_vars import get_str_env

ENCRYPTION_KEY_ENV_VAR = "FLEX_TOKEN_ENCRYPTION_KEY"  # noqa: S105  # nosec B105 — var name, not a secret

_HELP = (
    f"Set {ENCRYPTION_KEY_ENV_VAR} to a comma-separated list of Fernet keys "
    "(newest first). Generate one with `uv run python scripts/manage_flex_tokens.py generate-key` "
    "and store it in 1Password like every other secret in this repo."
)

_cached_fernet: MultiFernet | None = None


class EncryptionKeyError(RuntimeError):
    """The configured encryption key set is missing or unusable."""


class DecryptionError(RuntimeError):
    """A stored value could not be decrypted with any configured key."""


def generate_key() -> str:
    """Mint a fresh Fernet key. The caller is responsible for not leaking it."""
    return Fernet.generate_key().decode("ascii")


def reset_cache() -> None:
    """Drop the cached key set so the next call re-reads the environment."""
    global _cached_fernet
    _cached_fernet = None


def key_count() -> int:
    """How many keys are configured. Useful for operator diagnostics."""
    return len(_load_keys())


def _load_keys() -> list[str]:
    raw = get_str_env(ENCRYPTION_KEY_ENV_VAR)
    keys = [part.strip() for part in (raw or "").split(",")]
    keys = [key for key in keys if key]
    if not keys:
        raise EncryptionKeyError(f"{ENCRYPTION_KEY_ENV_VAR} is not set or is empty. {_HELP}")
    return keys


def _get_fernet() -> MultiFernet:
    global _cached_fernet
    if _cached_fernet is not None:
        return _cached_fernet

    keys = _load_keys()
    fernets: list[Fernet] = []
    for index, key in enumerate(keys):
        try:
            fernets.append(Fernet(key))
        except (ValueError, TypeError) as exc:
            # Deliberately positional — never echo the key material itself.
            raise EncryptionKeyError(f"{ENCRYPTION_KEY_ENV_VAR} key #{index + 1} is not a valid Fernet key. {_HELP}") from exc

    _cached_fernet = MultiFernet(fernets)
    return _cached_fernet


def encrypt(plaintext: str) -> str:
    """Encrypt under the primary (first) configured key."""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt with whichever configured key the value was written under."""
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            f"Stored value could not be decrypted with any key in {ENCRYPTION_KEY_ENV_VAR}. "
            "The key set is wrong, or the value was written under a key that has since been dropped."
        ) from exc


def rotate(ciphertext: str) -> str:
    """Re-encrypt an existing value under the primary key."""
    try:
        return _get_fernet().rotate(ciphertext.encode("ascii")).decode("ascii")
    except InvalidToken as exc:
        raise DecryptionError(f"Stored value could not be re-encrypted: no key in {ENCRYPTION_KEY_ENV_VAR} decrypts it.") from exc


def fingerprint(plaintext: str) -> str:
    """A short, non-reversible label for a secret, safe to print or log.

    Twelve hex characters of SHA-256 — enough to tell two tokens apart or to
    confirm a rotation preserved a value, and far too little to attack.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()[:12]
