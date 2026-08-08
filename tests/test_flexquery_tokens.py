"""Encrypted token storage, credential resolution, and account stamping.

The load-bearing assertion here is `test_raw_column_holds_ciphertext`: it reads
`token_encrypted` with raw SQL, bypassing the ORM's decrypting column type, and
proves that a reader with database access but no key cannot recover the token.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.models import Account, FlexQueryToken
from src.services import flex_credentials
from src.services.sync_common import _ensure_account, get_or_create_accounts
from src.utils import crypto

TOKEN_VALUE = "flex-token-value-abc"  # noqa: S105  # nosec B105 — fixture value, not a credential
OTHER_TOKEN_VALUE = "flex-token-value-xyz"  # noqa: S105  # nosec B105


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(crypto.ENCRYPTION_KEY_ENV_VAR, crypto.generate_key())
    crypto.reset_cache()
    yield
    crypto.reset_cache()


def _add_token(session: Session, name: str, value: str, *, report_id: str = "123456", active: bool = True) -> FlexQueryToken:
    row = FlexQueryToken(name=name, token_encrypted=value, report_id=report_id, is_active=active)
    session.add(row)
    session.flush()
    return row


def test_token_round_trips_through_the_model(db_session: Session) -> None:
    row = _add_token(db_session, "main", TOKEN_VALUE)
    db_session.expire(row)
    assert row.token_encrypted == TOKEN_VALUE


def test_raw_column_holds_ciphertext(db_session: Session) -> None:
    """R2: database access without the key must not yield the token."""
    row = _add_token(db_session, "main", TOKEN_VALUE)

    stored = db_session.execute(
        text("SELECT token_encrypted FROM flexquery_tokens WHERE id = :id"),
        {"id": row.id},
    ).scalar_one()

    assert stored != TOKEN_VALUE
    assert TOKEN_VALUE not in stored
    assert crypto.decrypt(stored) == TOKEN_VALUE


def test_null_token_round_trips_as_null(db_session: Session) -> None:
    account = Account(account="U1234567")
    db_session.add(account)
    db_session.flush()
    assert account.flex_query_token_id is None


def test_list_active_credentials_skips_inactive(db_session: Session) -> None:
    _add_token(db_session, "main", TOKEN_VALUE)
    _add_token(db_session, "retired", OTHER_TOKEN_VALUE, active=False)

    credentials = flex_credentials.list_active_credentials(db_session)

    assert [c.name for c in credentials] == ["main"]
    assert credentials[0].token == TOKEN_VALUE


def test_get_credential_by_name(db_session: Session) -> None:
    _add_token(db_session, "main", TOKEN_VALUE)
    _add_token(db_session, "lp", OTHER_TOKEN_VALUE, report_id="654321")

    credential = flex_credentials.get_credential_by_name(db_session, "lp")

    assert credential.token == OTHER_TOKEN_VALUE
    assert credential.report_id == "654321"


def test_get_credential_by_name_rejects_inactive(db_session: Session) -> None:
    _add_token(db_session, "retired", TOKEN_VALUE, active=False)
    with pytest.raises(flex_credentials.NoFlexCredentialsError, match="retired"):
        flex_credentials.get_credential_by_name(db_session, "retired")


def test_redact_strips_the_token_from_a_message(db_session: Session) -> None:
    """R14: a third-party error that echoes the token must not be stored raw."""
    _add_token(db_session, "main", TOKEN_VALUE)
    credential = flex_credentials.list_active_credentials(db_session)[0]

    redacted = credential.redact(f"HTTP 401 rejecting token={TOKEN_VALUE}")

    assert TOKEN_VALUE not in redacted
    assert flex_credentials.REDACTED in redacted


def test_new_account_is_stamped_with_its_token(db_session: Session) -> None:
    token = _add_token(db_session, "main", TOKEN_VALUE)
    account = _ensure_account(db_session, "U1234567", token.id)
    assert account.flex_query_token_id == token.id


def test_existing_unstamped_account_is_stamped_on_next_sync(db_session: Session) -> None:
    token = _add_token(db_session, "main", TOKEN_VALUE)
    _ensure_account(db_session, "U1234567")

    account = _ensure_account(db_session, "U1234567", token.id)

    assert account.flex_query_token_id == token.id


def test_account_moving_between_tokens_is_restamped(db_session: Session) -> None:
    """Last writer wins — an account genuinely moving must not stall the run."""
    first = _add_token(db_session, "main", TOKEN_VALUE)
    second = _add_token(db_session, "lp", OTHER_TOKEN_VALUE)

    _ensure_account(db_session, "U1234567", first.id)
    account = _ensure_account(db_session, "U1234567", second.id)

    assert account.flex_query_token_id == second.id


def test_non_flexquery_callers_leave_the_stamp_alone(db_session: Session) -> None:
    """sync_common is shared with TWS paths; they must not clear a stamp."""
    token = _add_token(db_session, "main", TOKEN_VALUE)
    _ensure_account(db_session, "U1234567", token.id)

    account = _ensure_account(db_session, "U1234567")

    assert account.flex_query_token_id == token.id


def test_get_or_create_accounts_stamps_and_returns_ids(db_session: Session) -> None:
    token = _add_token(db_session, "main", TOKEN_VALUE)

    lookup = get_or_create_accounts(db_session, {"U1234567", "U9999999"}, token.id)

    assert set(lookup) == {"U1234567", "U9999999"}
    for account_id in lookup.values():
        assert db_session.get(Account, account_id).flex_query_token_id == token.id


def test_get_or_create_accounts_without_a_token_leaves_null(db_session: Session) -> None:
    lookup = get_or_create_accounts(db_session, {"U1234567"})
    assert db_session.get(Account, lookup["U1234567"]).flex_query_token_id is None
