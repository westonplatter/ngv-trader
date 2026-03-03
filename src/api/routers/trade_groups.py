"""Trade group and tagging API router."""

from datetime import datetime, timezone
from decimal import Decimal
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.models import (
    Tag,
    TagLink,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
    TradeGroupExecutionEvent,
    TradeGroupLink,
)

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

TAG_TYPES = {"theme", "strategy", "risk_intent", "hedge_type", "holding_horizon"}
ENTITY_TYPES = {"orders", "trades", "trade_executions", "trade_groups"}
GROUP_STATUSES = {"open", "closed", "archived"}
ASSIGNMENT_SOURCES = {"manual", "rule", "agent"}


def _normalize_tag_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _ensure_group(db: Session, trade_group_id: int) -> TradeGroup:
    group = db.get(TradeGroup, trade_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Trade group not found")
    return group


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class TagResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    tag_type: str
    value: str
    normalized_value: str
    created_by: str
    created_at: datetime


class TagLinkResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    entity_type: str
    entity_id: int
    tag_id: int
    tag_type: str
    is_primary: bool
    source: str
    created_by: str
    confidence: float | None
    assigned_at: datetime
    created_at: datetime


class TradeGroupResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    name: str
    notes: str | None
    status: str
    opened_at: datetime
    closed_at: datetime | None
    opened_by: str | None
    closed_by: str | None
    created_at: datetime
    updated_at: datetime


class TradeGroupDetailResponse(TradeGroupResponse):
    tags: list[TagLinkResponse]
    execution_count: int


class TradeGroupCreateRequest(BaseModel):
    account_id: int
    name: str
    notes: str | None = None
    strategy_tag_id: int | None = None
    source: str = "manual"
    created_by: str = "api"
    confidence: float | None = None
    opened_at: datetime | None = None


class TradeGroupPatchRequest(BaseModel):
    name: str | None = None
    notes: str | None = None
    status: str | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None


class ExecutionAssignRequest(BaseModel):
    execution_ids: list[int] = Field(min_length=1)
    source: str
    created_by: str
    confidence: float | None = None
    reason: str | None = None
    force_reassign: bool = False


class ExecutionUnassignRequest(BaseModel):
    execution_ids: list[int] = Field(min_length=1)
    source: str
    created_by: str
    reason: str | None = None


class ExecutionReassignRequest(BaseModel):
    to_trade_group_id: int
    source: str
    created_by: str
    confidence: float | None = None
    reason: str | None = None


class TagCreateRequest(BaseModel):
    tag_type: str
    value: str
    created_by: str


class TagLinkCreateRequest(BaseModel):
    entity_type: str
    entity_id: int
    tag_id: int
    is_primary: bool = False
    source: str
    created_by: str
    confidence: float | None = None


class TimelineEventResponse(BaseModel):
    event_id: str
    event_type: str
    occurred_at: datetime
    execution_id: int | None
    related_trade_group_id: int | None
    summary: str
    provenance: dict
    metadata: dict | None = None


class TimelineResponse(BaseModel):
    trade_group_id: int
    events: list[TimelineEventResponse]


class ReportRow(BaseModel):
    key: str
    notional: float
    commission: float


class ReportResponse(BaseModel):
    group_by: str
    rows: list[ReportRow]


@router.get("/trade-groups", response_model=list[TradeGroupResponse])
def list_trade_groups(  # noqa: PLR0913
    account_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    strategy_tag: str | None = Query(default=None),
    theme_tag: str | None = Query(default=None),
    opened_from: datetime | None = Query(default=None),
    opened_to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(TradeGroup)
    if account_id is not None:
        stmt = stmt.where(TradeGroup.account_id == account_id)
    if status_filter is not None:
        stmt = stmt.where(TradeGroup.status == status_filter)
    if opened_from is not None:
        stmt = stmt.where(TradeGroup.opened_at >= opened_from)
    if opened_to is not None:
        stmt = stmt.where(TradeGroup.opened_at <= opened_to)

    if strategy_tag:
        normalized = _normalize_tag_value(strategy_tag)
        stmt = stmt.where(
            select(TagLink.id)
            .join(Tag, Tag.id == TagLink.tag_id)
            .where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == TradeGroup.id,
                    TagLink.tag_type == "strategy",
                    Tag.normalized_value == normalized,
                )
            )
            .exists()
        )

    if theme_tag:
        normalized = _normalize_tag_value(theme_tag)
        stmt = stmt.where(
            select(TagLink.id)
            .join(Tag, Tag.id == TagLink.tag_id)
            .where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == TradeGroup.id,
                    TagLink.tag_type == "theme",
                    Tag.normalized_value == normalized,
                )
            )
            .exists()
        )

    rows = (
        db.execute(stmt.order_by(TradeGroup.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )
    return [TradeGroupResponse.model_validate(row) for row in rows]


@router.post("/trade-groups", response_model=TradeGroupResponse, status_code=201)
def create_trade_group(
    body: TradeGroupCreateRequest, db: Session = DB_SESSION_DEPENDENCY
):
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    opened_at = body.opened_at or _now_utc()
    trade_group = TradeGroup(
        account_id=body.account_id,
        name=body.name,
        notes=body.notes,
        status="open",
        opened_at=opened_at,
        opened_by=body.created_by,
        created_at=_now_utc(),
        updated_at=_now_utc(),
    )
    db.add(trade_group)
    db.flush()

    if body.strategy_tag_id is not None:
        strategy_tag = db.get(Tag, body.strategy_tag_id)
        if strategy_tag is None:
            raise HTTPException(status_code=404, detail="Strategy tag not found")
        if strategy_tag.tag_type != "strategy":
            raise HTTPException(
                status_code=400, detail="strategy_tag_id must reference a strategy tag"
            )
        db.add(
            TagLink(
                entity_type="trade_groups",
                entity_id=trade_group.id,
                tag_id=strategy_tag.id,
                tag_type="strategy",
                is_primary=True,
                source=body.source,
                created_by=body.created_by,
                confidence=body.confidence,
                assigned_at=_now_utc(),
                created_at=_now_utc(),
            )
        )

    db.commit()
    db.refresh(trade_group)
    return TradeGroupResponse.model_validate(trade_group)


@router.get("/trade-groups/{trade_group_id}", response_model=TradeGroupDetailResponse)
def get_trade_group(trade_group_id: int, db: Session = DB_SESSION_DEPENDENCY):
    trade_group = _ensure_group(db, trade_group_id)
    tag_links = (
        db.execute(
            select(TagLink).where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == trade_group_id,
                )
            )
        )
        .scalars()
        .all()
    )
    execution_count = db.execute(
        select(func.count())
        .select_from(TradeGroupExecution)
        .where(TradeGroupExecution.trade_group_id == trade_group_id)
    ).scalar_one()

    return TradeGroupDetailResponse(
        **TradeGroupResponse.model_validate(trade_group).model_dump(),
        tags=[TagLinkResponse.model_validate(row) for row in tag_links],
        execution_count=execution_count,
    )


@router.patch("/trade-groups/{trade_group_id}", response_model=TradeGroupResponse)
def patch_trade_group(
    trade_group_id: int,
    body: TradeGroupPatchRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    trade_group = _ensure_group(db, trade_group_id)

    if body.status is not None:
        if body.status not in GROUP_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid trade group status")
        trade_group.status = body.status
    if body.name is not None:
        trade_group.name = body.name
    if body.notes is not None:
        trade_group.notes = body.notes
    if body.closed_by is not None:
        trade_group.closed_by = body.closed_by

    if body.closed_at is not None:
        trade_group.closed_at = body.closed_at

    trade_group.updated_at = _now_utc()
    db.add(trade_group)
    db.commit()
    db.refresh(trade_group)
    return TradeGroupResponse.model_validate(trade_group)


@router.delete("/trade-groups/{trade_group_id}", status_code=204)
def delete_trade_group(
    trade_group_id: int,
    response: Response,
    source: str = Query(default="manual"),
    created_by: str = Query(default="api"),
    reason: str | None = Query(default="trade group deleted"),
    db: Session = DB_SESSION_DEPENDENCY,
):
    if source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    _ensure_group(db, trade_group_id)
    assignments = (
        db.execute(
            select(TradeGroupExecution).where(
                TradeGroupExecution.trade_group_id == trade_group_id
            )
        )
        .scalars()
        .all()
    )

    for assignment in assignments:
        db.add(
            TradeGroupExecutionEvent(
                trade_execution_id=assignment.trade_execution_id,
                from_trade_group_id=trade_group_id,
                to_trade_group_id=None,
                event_type="unassigned",
                source=source,
                created_by=created_by,
                reason=reason,
                event_at=_now_utc(),
            )
        )
        db.delete(assignment)

    db.query(TagLink).filter(
        TagLink.entity_type == "trade_groups", TagLink.entity_id == trade_group_id
    ).delete()
    db.query(TradeGroupLink).filter(
        or_(
            TradeGroupLink.parent_trade_group_id == trade_group_id,
            TradeGroupLink.child_trade_group_id == trade_group_id,
        )
    ).delete()
    db.query(TradeGroup).filter(TradeGroup.id == trade_group_id).delete()
    db.commit()
    response.status_code = 204
    return response


@router.post("/trade-groups/{trade_group_id}/executions:assign", status_code=204)
def assign_executions(
    trade_group_id: int,
    body: ExecutionAssignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    trade_group = _ensure_group(db, trade_group_id)
    executions = (
        db.execute(
            select(TradeExecution).where(TradeExecution.id.in_(body.execution_ids))
        )
        .scalars()
        .all()
    )
    if len(executions) != len(set(body.execution_ids)):
        raise HTTPException(status_code=404, detail="One or more executions not found")

    for execution in executions:
        if execution.account_id != trade_group.account_id:
            raise HTTPException(
                status_code=400,
                detail="Execution account does not match trade group account",
            )

        existing = db.execute(
            select(TradeGroupExecution).where(
                TradeGroupExecution.trade_execution_id == execution.id
            )
        ).scalar_one_or_none()
        if existing and existing.trade_group_id == trade_group_id:
            continue
        if existing and not body.force_reassign:
            raise HTTPException(
                status_code=409, detail=f"Execution {execution.id} already assigned"
            )

        if existing:
            previous_group_id = existing.trade_group_id
            existing.trade_group_id = trade_group_id
            existing.source = body.source
            existing.created_by = body.created_by
            existing.confidence = body.confidence
            existing.assigned_at = _now_utc()
            event_type = "reassigned"
        else:
            db.add(
                TradeGroupExecution(
                    trade_group_id=trade_group_id,
                    trade_execution_id=execution.id,
                    source=body.source,
                    created_by=body.created_by,
                    confidence=body.confidence,
                    assigned_at=_now_utc(),
                )
            )
            previous_group_id = None
            event_type = "assigned"

        db.add(
            TradeGroupExecutionEvent(
                trade_execution_id=execution.id,
                from_trade_group_id=previous_group_id,
                to_trade_group_id=trade_group_id,
                event_type=event_type,
                source=body.source,
                created_by=body.created_by,
                confidence=body.confidence,
                reason=body.reason,
                event_at=_now_utc(),
            )
        )

    db.commit()


@router.post("/trade-groups/{trade_group_id}/executions:unassign", status_code=204)
def unassign_executions(
    trade_group_id: int,
    body: ExecutionUnassignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    _ensure_group(db, trade_group_id)
    assignments = (
        db.execute(
            select(TradeGroupExecution).where(
                and_(
                    TradeGroupExecution.trade_group_id == trade_group_id,
                    TradeGroupExecution.trade_execution_id.in_(body.execution_ids),
                )
            )
        )
        .scalars()
        .all()
    )

    for assignment in assignments:
        db.add(
            TradeGroupExecutionEvent(
                trade_execution_id=assignment.trade_execution_id,
                from_trade_group_id=trade_group_id,
                to_trade_group_id=None,
                event_type="unassigned",
                source=body.source,
                created_by=body.created_by,
                reason=body.reason,
                event_at=_now_utc(),
            )
        )
        db.delete(assignment)

    db.commit()


@router.post("/trade-executions/{execution_id}/trade-group:reassign", status_code=204)
def reassign_execution(
    execution_id: int,
    body: ExecutionReassignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    assign_executions(
        trade_group_id=body.to_trade_group_id,
        body=ExecutionAssignRequest(
            execution_ids=[execution_id],
            source=body.source,
            created_by=body.created_by,
            confidence=body.confidence,
            reason=body.reason,
            force_reassign=True,
        ),
        db=db,
    )


@router.get("/trade-groups/{trade_group_id}/timeline", response_model=TimelineResponse)
def trade_group_timeline(trade_group_id: int, db: Session = DB_SESSION_DEPENDENCY):  # noqa: PLR0912
    _ensure_group(db, trade_group_id)

    events: list[TimelineEventResponse] = []

    execution_rows = db.execute(
        select(TradeGroupExecution, TradeExecution)
        .join(
            TradeExecution,
            TradeExecution.id == TradeGroupExecution.trade_execution_id,
        )
        .where(TradeGroupExecution.trade_group_id == trade_group_id)
        .order_by(TradeExecution.executed_at.asc(), TradeExecution.id.asc())
    ).all()

    for assignment, execution in execution_rows:
        if execution.exec_role == "leg":
            event_type = "adjustment_execution"
        elif execution.side and execution.side.upper() in {"BOT", "BUY"}:
            event_type = "entry_execution"
        else:
            event_type = "exit_execution"
        events.append(
            TimelineEventResponse(
                event_id=f"assign-{execution.id}",
                event_type=event_type,
                occurred_at=execution.executed_at,
                execution_id=execution.id,
                related_trade_group_id=None,
                summary=f"Execution {execution.id} {execution.side or 'UNKNOWN'} qty={execution.quantity}",
                provenance={
                    "source": assignment.source,
                    "created_by": assignment.created_by,
                    "confidence": assignment.confidence,
                },
                metadata={"exec_role": execution.exec_role},
            )
        )

    history_rows = (
        db.execute(
            select(TradeGroupExecutionEvent)
            .where(
                or_(
                    TradeGroupExecutionEvent.from_trade_group_id == trade_group_id,
                    TradeGroupExecutionEvent.to_trade_group_id == trade_group_id,
                )
            )
            .order_by(
                TradeGroupExecutionEvent.event_at.asc(),
                TradeGroupExecutionEvent.id.asc(),
            )
        )
        .scalars()
        .all()
    )

    for row in history_rows:
        if row.event_type == "reassigned":
            event_type = (
                "execution_reassigned_in"
                if row.to_trade_group_id == trade_group_id
                else "execution_reassigned_out"
            )
        elif row.event_type == "unassigned":
            event_type = "execution_unassigned"
        else:
            event_type = "adjustment_execution"
        events.append(
            TimelineEventResponse(
                event_id=f"event-{row.id}",
                event_type=event_type,
                occurred_at=row.event_at,
                execution_id=row.trade_execution_id,
                related_trade_group_id=row.from_trade_group_id
                if row.to_trade_group_id == trade_group_id
                else row.to_trade_group_id,
                summary=f"Execution {row.trade_execution_id} {row.event_type}",
                provenance={
                    "source": row.source,
                    "created_by": row.created_by,
                    "confidence": row.confidence,
                },
                metadata={"reason": row.reason},
            )
        )

    link_rows = (
        db.execute(
            select(TradeGroupLink)
            .where(
                or_(
                    TradeGroupLink.parent_trade_group_id == trade_group_id,
                    TradeGroupLink.child_trade_group_id == trade_group_id,
                )
            )
            .order_by(TradeGroupLink.created_at.asc(), TradeGroupLink.id.asc())
        )
        .scalars()
        .all()
    )

    for link in link_rows:
        related_id = (
            link.parent_trade_group_id
            if link.child_trade_group_id == trade_group_id
            else link.child_trade_group_id
        )
        events.append(
            TimelineEventResponse(
                event_id=f"link-{link.id}",
                event_type="roll_linked",
                occurred_at=link.created_at,
                execution_id=None,
                related_trade_group_id=related_id,
                summary=f"Trade Group {trade_group_id} {link.link_type} {related_id}",
                provenance={
                    "source": "manual",
                    "created_by": link.created_by,
                    "confidence": None,
                },
                metadata={"link_type": link.link_type},
            )
        )

    events.sort(key=lambda item: (item.occurred_at, item.event_id))
    return TimelineResponse(trade_group_id=trade_group_id, events=events)


@router.get("/tags", response_model=list[TagResponse])
def list_tags(
    tag_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = DB_SESSION_DEPENDENCY,
):
    stmt = select(Tag)
    if tag_type is not None:
        stmt = stmt.where(Tag.tag_type == tag_type)
    if q:
        stmt = stmt.where(Tag.normalized_value.like(f"%{_normalize_tag_value(q)}%"))
    rows = db.execute(stmt.order_by(Tag.created_at.desc()).limit(limit)).scalars().all()
    return [TagResponse.model_validate(row) for row in rows]


@router.post("/tags", response_model=TagResponse, status_code=201)
def create_tag(body: TagCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    if body.tag_type not in TAG_TYPES:
        raise HTTPException(status_code=400, detail="Invalid tag_type")
    normalized_value = _normalize_tag_value(body.value)

    existing = db.execute(
        select(Tag).where(
            and_(
                Tag.tag_type == body.tag_type, Tag.normalized_value == normalized_value
            )
        )
    ).scalar_one_or_none()
    if existing:
        return TagResponse.model_validate(existing)

    tag = Tag(
        tag_type=body.tag_type,
        value=body.value.strip(),
        normalized_value=normalized_value,
        created_by=body.created_by,
        created_at=_now_utc(),
    )
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return TagResponse.model_validate(tag)


@router.post("/tag-links", response_model=TagLinkResponse, status_code=201)
def create_tag_link(body: TagLinkCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    if body.entity_type not in ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="Invalid entity_type")
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    tag = db.get(Tag, body.tag_id)
    if tag is None:
        raise HTTPException(status_code=404, detail="Tag not found")

    tag_link = TagLink(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        tag_id=body.tag_id,
        tag_type=tag.tag_type,
        is_primary=body.is_primary,
        source=body.source,
        created_by=body.created_by,
        confidence=body.confidence,
        assigned_at=_now_utc(),
        created_at=_now_utc(),
    )

    if (
        body.entity_type == "trade_groups"
        and tag.tag_type == "strategy"
        and body.is_primary
        and db.execute(
            select(TagLink).where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == body.entity_id,
                    TagLink.tag_type == "strategy",
                    TagLink.is_primary.is_(True),
                )
            )
        ).scalar_one_or_none()
    ):
        raise HTTPException(
            status_code=409, detail="Trade group already has a primary strategy"
        )

    db.add(tag_link)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tag link conflict") from exc
    db.refresh(tag_link)
    return TagLinkResponse.model_validate(tag_link)


@router.delete("/tag-links/{tag_link_id}", status_code=204)
def delete_tag_link(
    tag_link_id: int, response: Response, db: Session = DB_SESSION_DEPENDENCY
):
    tag_link = db.get(TagLink, tag_link_id)
    if tag_link is None:
        raise HTTPException(status_code=404, detail="Tag link not found")
    db.delete(tag_link)
    db.commit()
    response.status_code = 204
    return response


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
            func.coalesce(
                func.sum(func.abs(TradeExecution.quantity * TradeExecution.price)), 0
            ).label("notional"),
            func.coalesce(func.sum(TradeExecution.commission), 0).label("commission"),
        )
        .select_from(TradeGroupExecution)
        .join(
            TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id
        )
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
            .where(
                and_(
                    TagLink.entity_type == "trade_groups", TagLink.tag_type == tag_type
                )
            )
        ).all()
        totals: dict[str, dict[str, float]] = {}
        for group_id, tag_value in tag_rows:
            if group_id not in metrics:
                continue
            bucket = totals.setdefault(tag_value, {"notional": 0.0, "commission": 0.0})
            bucket["notional"] += metrics[group_id]["notional"]
            bucket["commission"] += metrics[group_id]["commission"]

        for key, value in totals.items():
            rows.append(
                ReportRow(
                    key=key, notional=value["notional"], commission=value["commission"]
                )
            )

    if include_hedge_adjusted:
        for row in rows:
            row.notional = float(
                Decimal(str(row.notional)) - Decimal(str(row.commission))
            )

    return ReportResponse(group_by=group_by, rows=rows)
