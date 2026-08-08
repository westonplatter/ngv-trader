"""IBKR FlexQuery token management.

The token value is **write-only**: it is accepted on create and update, and is
never returned by any endpoint here. Reads deliberately do not decrypt, so a
plain listing needs no encryption key at all — only writes do.

`scripts/manage_flex_tokens.py` remains the way to generate and rotate the
encryption key itself, which never passes through the API.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, FlexQueryToken
from src.utils.crypto import EncryptionKeyError

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class FlexQueryTokenResponse(BaseModel):
    """Everything about a token except the token."""

    id: int
    name: str
    report_id: str
    is_active: bool
    notes: str | None
    last_used_at: datetime | None
    account_count: int


class FlexQueryTokenCreate(BaseModel):
    name: str = Field(min_length=1, description="Operator label, unique")
    report_id: str = Field(min_length=1, description="IBKR FlexQuery report id")
    token: SecretStr = Field(min_length=1, description="Write-only; never returned")
    notes: str | None = None


class FlexQueryTokenUpdate(BaseModel):
    """Every field optional. A blank or omitted `token` leaves the stored one alone."""

    name: str | None = Field(default=None, min_length=1)
    report_id: str | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    notes: str | None = None
    token: SecretStr | None = None


def _account_counts(db: Session) -> dict[int, int]:
    rows = db.execute(
        select(Account.flex_query_token_id, func.count(Account.id)).where(Account.flex_query_token_id.is_not(None)).group_by(Account.flex_query_token_id)
    ).all()
    return {token_id: count for token_id, count in rows}


def _to_response(row: FlexQueryToken, counts: dict[int, int]) -> FlexQueryTokenResponse:
    return FlexQueryTokenResponse(
        id=row.id,
        name=row.name,
        report_id=row.report_id,
        is_active=row.is_active,
        notes=row.notes,
        last_used_at=row.last_used_at,
        account_count=counts.get(row.id, 0),
    )


def _commit(db: Session, name: str) -> None:
    """Commit, converting the failures a caller can cause into clean responses.

    Nothing raised from here may chain the underlying SQLAlchemy error. A
    failure encrypting the bind parameter surfaces as a `StatementError` whose
    message embeds the parameters — the token among them — so it must never
    reach a traceback or a response body. Hence `from None` throughout.
    """
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"A token named {name!r} already exists.") from None
    except StatementError as exc:
        db.rollback()
        # The encryption-key error names the env var and carries no key or
        # token material, so its own message is safe to surface.
        if isinstance(exc.orig, EncryptionKeyError):
            raise HTTPException(status_code=503, detail=str(exc.orig)) from None
        raise HTTPException(
            status_code=500,
            detail=f"Could not store the token ({type(exc.orig).__name__ if exc.orig else type(exc).__name__}).",
        ) from None


@router.get("/flexquery-tokens", response_model=list[FlexQueryTokenResponse])
def list_flexquery_tokens(db: Session = DB_SESSION_DEPENDENCY):
    counts = _account_counts(db)
    rows = db.execute(select(FlexQueryToken).order_by(FlexQueryToken.id)).scalars().all()
    return [_to_response(row, counts) for row in rows]


@router.post("/flexquery-tokens", response_model=FlexQueryTokenResponse, status_code=201)
def create_flexquery_token(body: FlexQueryTokenCreate, db: Session = DB_SESSION_DEPENDENCY):
    now = datetime.now(timezone.utc)
    row = FlexQueryToken(
        name=body.name,
        token_encrypted=body.token.get_secret_value(),
        report_id=body.report_id,
        is_active=True,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    _commit(db, body.name)
    db.refresh(row)
    return _to_response(row, _account_counts(db))


@router.patch("/flexquery-tokens/{token_id}", response_model=FlexQueryTokenResponse)
def update_flexquery_token(token_id: int, body: FlexQueryTokenUpdate, db: Session = DB_SESSION_DEPENDENCY):
    row = db.get(FlexQueryToken, token_id)
    if not row:
        raise HTTPException(status_code=404, detail="Token not found")

    if body.name is not None:
        row.name = body.name
    if body.report_id is not None:
        row.report_id = body.report_id
    if body.is_active is not None:
        row.is_active = body.is_active
    if body.notes is not None:
        row.notes = body.notes
    if body.token is not None and body.token.get_secret_value().strip():
        row.token_encrypted = body.token.get_secret_value().strip()
    row.updated_at = datetime.now(timezone.utc)

    _commit(db, row.name)
    db.refresh(row)
    return _to_response(row, _account_counts(db))
