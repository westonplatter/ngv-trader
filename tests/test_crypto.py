"""Fernet key handling for secrets stored at rest.

These tests own the guarantees the token table depends on: values survive a
round trip, a rotation does not strand data, and a misconfigured key produces a
named error rather than a `cryptography` traceback — with no key or plaintext
material in the message.
"""

import pytest
from cryptography.fernet import Fernet

from src.utils import crypto

SECRET = "flex-token-under-test"  # noqa: S105  # nosec B105 — fixture value, not a credential


@pytest.fixture(autouse=True)
def _clear_key_cache() -> None:
    """The key set is cached at module scope; each test configures its own."""
    crypto.reset_cache()
    yield
    crypto.reset_cache()


def _set_keys(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV_VAR, ",".join(keys))
    crypto.reset_cache()


def test_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_keys(monkeypatch, crypto.generate_key())
    assert crypto.decrypt(crypto.encrypt(SECRET)) == SECRET


def test_ciphertext_is_not_the_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_keys(monkeypatch, crypto.generate_key())
    ciphertext = crypto.encrypt(SECRET)
    assert SECRET not in ciphertext
    assert ciphertext.startswith("gAAAAA")


def test_decrypts_under_a_secondary_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """A value written under the old key still reads once a new key is prepended."""
    old, new = crypto.generate_key(), crypto.generate_key()
    _set_keys(monkeypatch, old)
    written = crypto.encrypt(SECRET)

    _set_keys(monkeypatch, new, old)
    assert crypto.decrypt(written) == SECRET


def test_rotate_rewrites_under_the_primary_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """After rotate, the old key can be dropped without stranding the value."""
    old, new = crypto.generate_key(), crypto.generate_key()
    _set_keys(monkeypatch, old)
    written = crypto.encrypt(SECRET)

    _set_keys(monkeypatch, new, old)
    rotated = crypto.rotate(written)

    _set_keys(monkeypatch, new)
    assert crypto.decrypt(rotated) == SECRET
    with pytest.raises(crypto.DecryptionError):
        crypto.decrypt(written)


def test_whitespace_and_empty_entries_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    key = crypto.generate_key()
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV_VAR, f" {key} , ")
    crypto.reset_cache()
    assert crypto.key_count() == 1
    assert crypto.decrypt(crypto.encrypt(SECRET)) == SECRET


def test_unset_key_raises_a_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(crypto.ENCRYPTION_KEY_ENV_VAR, raising=False)
    crypto.reset_cache()
    with pytest.raises(crypto.EncryptionKeyError, match=crypto.ENCRYPTION_KEY_ENV_VAR):
        crypto.encrypt(SECRET)


def test_malformed_key_raises_a_named_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad key must not surface as a binascii/ValueError from cryptography."""
    _set_keys(monkeypatch, "not-a-valid-fernet-key")
    with pytest.raises(crypto.EncryptionKeyError, match=crypto.ENCRYPTION_KEY_ENV_VAR):
        crypto.encrypt(SECRET)


def test_errors_never_carry_key_or_plaintext(monkeypatch: pytest.MonkeyPatch) -> None:
    bad_key = Fernet.generate_key().decode("ascii")
    _set_keys(monkeypatch, bad_key)
    ciphertext = crypto.encrypt(SECRET)

    _set_keys(monkeypatch, crypto.generate_key())
    with pytest.raises(crypto.DecryptionError) as excinfo:
        crypto.decrypt(ciphertext)

    message = str(excinfo.value)
    assert SECRET not in message
    assert bad_key not in message


def test_fingerprint_is_stable_and_not_reversible() -> None:
    assert crypto.fingerprint(SECRET) == crypto.fingerprint(SECRET)
    assert crypto.fingerprint(SECRET) != crypto.fingerprint(SECRET + "x")
    assert SECRET not in crypto.fingerprint(SECRET)
    assert len(crypto.fingerprint(SECRET)) == 12
