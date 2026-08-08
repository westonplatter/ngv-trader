"""Accounts API router."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account, FlexQueryToken
from src.utils.ibkr_account import mask_ibkr_account

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class AccountResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account: str
    masked_account: str | None = None
    alias: str | None
    # Which FlexQuery token this account was last discovered under. The token
    # *value* never leaves the database — only its operator label.
    flex_query_token_id: int | None = None
    flex_query_token_name: str | None = None

    def model_post_init(self, __context: object) -> None:
        if self.masked_account is None:
            self.masked_account = mask_ibkr_account(self.account)


class AccountUpdate(BaseModel):
    alias: str | None


def _token_names(db: Session) -> dict[int, str]:
    """id -> operator label for every token. A handful of rows, so no join needed."""
    return {row.id: row.name for row in db.execute(select(FlexQueryToken)).scalars()}


def _to_response(account: Account, names: dict[int, str]) -> AccountResponse:
    response = AccountResponse.model_validate(account)
    if account.flex_query_token_id is not None:
        response.flex_query_token_name = names.get(account.flex_query_token_id)
    return response


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = DB_SESSION_DEPENDENCY):
    names = _token_names(db)
    return [_to_response(account, names) for account in db.execute(select(Account)).scalars().all()]


@router.get("/accounts/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = DB_SESSION_DEPENDENCY):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return _to_response(account, _token_names(db))


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, body: AccountUpdate, db: Session = DB_SESSION_DEPENDENCY):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.alias = body.alias
    db.commit()
    db.refresh(account)
    return _to_response(account, _token_names(db))
