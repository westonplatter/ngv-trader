"""User preferences API router."""

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import UserPreference

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class PreferenceResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    key: str
    value: Any
    created_at: datetime
    updated_at: datetime


class PreferenceUpsertRequest(BaseModel):
    value: Any


@router.get("/user-preferences", response_model=list[PreferenceResponse])
def list_preferences(db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(UserPreference).order_by(UserPreference.key)
    rows = db.scalars(stmt).all()
    return rows


@router.get("/user-preferences/{key}", response_model=PreferenceResponse)
def get_preference(key: str, db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(UserPreference).where(UserPreference.key == key)
    pref = db.scalars(stmt).first()
    if pref is None:
        raise HTTPException(status_code=404, detail=f"Preference '{key}' not found")
    return pref


@router.put("/user-preferences/{key}", response_model=PreferenceResponse)
def upsert_preference(
    key: str,
    body: PreferenceUpsertRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(UserPreference).where(UserPreference.key == key)
    pref = db.scalars(stmt).first()
    now = datetime.now(timezone.utc)
    if pref is None:
        pref = UserPreference(key=key, value=body.value, created_at=now, updated_at=now)
        db.add(pref)
    else:
        pref.value = body.value
        pref.updated_at = now
    db.commit()
    db.refresh(pref)
    return pref


@router.delete("/user-preferences/{key}", status_code=204)
def delete_preference(key: str, db: Session = DB_SESSION_DEPENDENCY):
    stmt = select(UserPreference).where(UserPreference.key == key)
    pref = db.scalars(stmt).first()
    if pref is None:
        raise HTTPException(status_code=404, detail=f"Preference '{key}' not found")
    db.delete(pref)
    db.commit()
