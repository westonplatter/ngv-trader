"""Accounts API router."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Account
from src.utils.ibkr_account import mask_ibkr_account

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class AccountResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account: str
    masked_account: str | None = None
    alias: str | None

    def model_post_init(self, __context: object) -> None:
        if self.masked_account is None:
            self.masked_account = mask_ibkr_account(self.account)


class AccountUpdate(BaseModel):
    alias: str | None


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(db: Session = DB_SESSION_DEPENDENCY):
    result = db.execute(select(Account))
    return result.scalars().all()


@router.get("/accounts/{account_id}", response_model=AccountResponse)
def get_account(account_id: int, db: Session = DB_SESSION_DEPENDENCY):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, body: AccountUpdate, db: Session = DB_SESSION_DEPENDENCY):
    account = db.get(Account, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account.alias = body.alias
    db.commit()
    db.refresh(account)
    return account
