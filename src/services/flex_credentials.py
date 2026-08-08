"""Resolve IBKR FlexQuery credentials from the database.

Tokens live in ``flexquery_tokens`` encrypted at rest — not in the environment,
and not in a job payload. Seed and rotate rows with
``scripts/manage_flex_tokens.py``.

A token value must never reach a log line, an exception message, or a job
result — use ``FlexCredential.name`` to identify a token, and ``redact`` on any
third-party message that might have echoed the value back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.models import FlexQueryToken

REDACTED = "<redacted-flex-token>"  # noqa: S105  # nosec B105 — placeholder, not a secret

SEED_HINT = "Seed one with `uv run python scripts/manage_flex_tokens.py add --name <label> --report-id <id>`."


class NoFlexCredentialsError(RuntimeError):
    """No usable FlexQuery token is configured in the database."""


@dataclass(frozen=True)
class FlexCredential:
    """One token row, decrypted, ready to hand to the Flex client."""

    token_id: int
    name: str
    token: str
    report_id: str

    def redact(self, message: str) -> str:
        """Strip the token value out of a message before it is logged or stored."""
        return redact(message, self.token)


def redact(message: str, token: str) -> str:
    if not token:
        return message
    return message.replace(token, REDACTED)


def _to_credential(row: FlexQueryToken) -> FlexCredential:
    return FlexCredential(
        token_id=row.id,
        name=row.name,
        token=row.token_encrypted,
        report_id=row.report_id,
    )


def list_active_credentials(session: Session) -> list[FlexCredential]:
    """Every active token, oldest first, so ordering is stable across runs."""
    stmt = select(FlexQueryToken).where(FlexQueryToken.is_active.is_(True)).order_by(FlexQueryToken.id)
    return [_to_credential(row) for row in session.execute(stmt).scalars().all()]


def get_credential_by_name(session: Session, name: str) -> FlexCredential:
    stmt = select(FlexQueryToken).where(FlexQueryToken.name == name, FlexQueryToken.is_active.is_(True))
    row = session.execute(stmt).scalars().first()
    if row is None:
        raise NoFlexCredentialsError(f"No active FlexQuery token named {name!r}. {SEED_HINT}")
    return _to_credential(row)


def load_active_credentials(engine: Engine) -> list[FlexCredential]:
    """Active tokens for a sync run. Raises when the table has none."""
    with Session(engine) as session:
        credentials = list_active_credentials(session)
    if not credentials:
        raise NoFlexCredentialsError(f"No active FlexQuery tokens are configured. {SEED_HINT}")
    return credentials


def load_credential(engine: Engine, name: str | None = None) -> FlexCredential:
    """One credential: the named one, or the first active token."""
    with Session(engine) as session:
        if name:
            return get_credential_by_name(session, name)
        credentials = list_active_credentials(session)
    if not credentials:
        raise NoFlexCredentialsError(f"No active FlexQuery tokens are configured. {SEED_HINT}")
    return credentials[0]


def load_credential_by_id(engine: Engine, token_id: int) -> FlexCredential:
    """One active credential by primary key.

    Keyed on the id rather than the name so a job queued before a rename still
    resolves to the token it was created for.
    """
    with Session(engine) as session:
        row = session.get(FlexQueryToken, token_id)
        if row is None or not row.is_active:
            raise NoFlexCredentialsError(f"No active FlexQuery token with id {token_id}. {SEED_HINT}")
        return _to_credential(row)


def mark_used(engine: Engine, token_id: int) -> None:
    """Record that a token successfully returned a report."""
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        row = session.get(FlexQueryToken, token_id)
        if row is None:
            return
        row.last_used_at = now
        row.updated_at = now
        session.commit()
