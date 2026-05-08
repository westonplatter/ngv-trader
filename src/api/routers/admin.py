"""Admin API endpoints — operator-facing visibility into background jobs/syncs."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import FlexSyncLog

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class FlexSyncLogResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    start_date: date
    end_date: date
    fetched_at: datetime
    row_count: int | None
    status: str
    error_message: str | None


@router.get("/admin/flex-sync-log", response_model=list[FlexSyncLogResponse])
def list_flex_sync_log(
    account_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(FlexSyncLog).order_by(FlexSyncLog.id.desc()).limit(limit)
    if account_id is not None:
        stmt = stmt.where(FlexSyncLog.account_id == account_id)
    rows = db.execute(stmt).scalars().all()
    return [FlexSyncLogResponse.model_validate(row) for row in rows]
