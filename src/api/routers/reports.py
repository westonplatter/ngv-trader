"""Reports API router."""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import Tag, TagLink, TradeExecution, TradeGroup, TradeGroupExecution

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class ReportRow(BaseModel):
    key: str
    notional: float
    commission: float


class ReportResponse(BaseModel):
    group_by: str
    rows: list[ReportRow]


@router.get("/reports/pnl/trade-groups", response_model=ReportResponse)
def pnl_by_trade_groups(  # noqa: C901, PLR0912
    account_id: int | None = Query(default=None),
    group_by: str = Query(default="trade_group"),
    from_ts: datetime | None = Query(default=None, alias="from"),
    to_ts: datetime | None = Query(default=None, alias="to"),
    include_hedge_adjusted: bool = Query(default=False),
    db: Session = DB_SESSION_DEPENDENCY,
):
    if group_by not in {"theme", "strategy", "trade_group"}:
        raise HTTPException(status_code=400, detail="Invalid group_by")

    conditions = []
    if account_id is not None:
        conditions.append(TradeGroup.account_id == account_id)
    if from_ts is not None:
        conditions.append(TradeExecution.executed_at >= from_ts)
    if to_ts is not None:
        conditions.append(TradeExecution.executed_at <= to_ts)

    base_stmt = (
        select(
            TradeGroup.id.label("trade_group_id"),
            func.coalesce(func.sum(func.abs(TradeExecution.quantity * TradeExecution.price)), 0).label("notional"),
            func.coalesce(func.sum(TradeExecution.commission), 0).label("commission"),
        )
        .select_from(TradeGroupExecution)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .join(TradeGroup, TradeGroup.id == TradeGroupExecution.trade_group_id)
        .where(and_(*conditions) if conditions else True)
        .group_by(TradeGroup.id)
    )

    grouped_rows = db.execute(base_stmt).all()
    metrics = {
        row.trade_group_id: {
            "notional": float(row.notional or 0),
            "commission": float(row.commission or 0),
        }
        for row in grouped_rows
    }

    rows: list[ReportRow] = []
    if group_by == "trade_group":
        for key_id, value in metrics.items():
            rows.append(
                ReportRow(
                    key=f"trade_group:{key_id}",
                    notional=value["notional"],
                    commission=value["commission"],
                )
            )
    else:
        tag_type = "theme" if group_by == "theme" else "strategy"
        tag_rows = db.execute(
            select(TagLink.entity_id, Tag.value)
            .join(Tag, Tag.id == TagLink.tag_id)
            .where(and_(TagLink.entity_type == "trade_groups", TagLink.tag_type == tag_type))
        ).all()
        totals: dict[str, dict[str, float]] = {}
        for group_id, tag_value in tag_rows:
            if group_id not in metrics:
                continue
            bucket = totals.setdefault(tag_value, {"notional": 0.0, "commission": 0.0})
            bucket["notional"] += metrics[group_id]["notional"]
            bucket["commission"] += metrics[group_id]["commission"]

        for key, value in totals.items():
            rows.append(ReportRow(key=key, notional=value["notional"], commission=value["commission"]))

    if include_hedge_adjusted:
        for row in rows:
            row.notional = float(Decimal(str(row.notional)) - Decimal(str(row.commission)))

    return ReportResponse(group_by=group_by, rows=rows)
