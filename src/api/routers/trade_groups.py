"""Trade groups API router."""

from collections.abc import Iterable
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.routers.positions import _derive_option_expiry_and_dte
from src.api.routers.tags import TagLinkResponse, _normalize_tag_value
from src.api.routers.trades import (
    _contract_display_from_raw,
    _execution_ib_codes,
    _execution_realized_pnl,
)
from src.models import (
    Account,
    ContractRef,
    LatestOptionMetrics,
    LiveExecution,
    Tag,
    TagLink,
    Trade,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
    TradeGroupExecutionEvent,
    TradeGroupLink,
    TradeGroupLiveExecution,
)
from src.services.cl_contracts import infer_contract_month_from_local_symbol
from src.services.intraday_overlay import (
    dedupe_live_realized,
    intraday_unrealized_total,
    is_live_stale,
    merge_positions,
    overlay_totals,
)
from src.services.trade_group_meta import TradeGroupMetaError, parse_meta_yaml
from src.services.trade_group_pnl import (
    load_overlay_inputs,
    trade_group_realized_pnl,
    trade_group_total_pnls,
)
from src.services.ui_events import (
    TOPIC_POSITIONS,
    TOPIC_TRADES,
    broadcaster,
    make_coarse_event,
)
from src.utils.contract_display import contract_display_name

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)

GROUP_STATUSES = {"open", "closed", "archived"}
ASSIGNMENT_SOURCES = {"manual", "rule", "agent"}


def _ensure_group(db: Session, trade_group_id: int) -> TradeGroup:
    group = db.get(TradeGroup, trade_group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Trade group not found")
    return group


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_meta_or_400(raw: str | None) -> dict | None:
    """Validate/parse meta YAML, mapping malformed input to a 400."""
    try:
        return parse_meta_yaml(raw)
    except TradeGroupMetaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class TradeGroupResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int | None
    name: str
    notes: str | None
    meta_yaml: str | None = None
    status: str
    primary_strategy_value: str | None = None
    opened_at: datetime
    closed_at: datetime | None
    opened_by: str | None
    closed_by: str | None
    created_at: datetime
    updated_at: datetime
    # Settled Total PnL (realized + settled unrealized). Populated by the list
    # endpoint; None elsewhere (the detail view computes its own live figures).
    total_pnl: float | None = None


class TradeGroupDetailResponse(TradeGroupResponse):
    tags: list[TagLinkResponse]
    execution_count: int
    # Parsed, JSON-serializable form of ``meta_yaml`` (recognized blocks validated,
    # arbitrary keys passed through). ``None`` when no meta is set.
    meta: dict | None = None


class TradeGroupCreateRequest(BaseModel):
    name: str
    notes: str | None = None
    meta_yaml: str | None = None
    strategy_tag_id: int | None = None
    source: str = "manual"
    created_by: str = "api"
    confidence: float | None = None
    opened_at: datetime | None = None


class TradeGroupPatchRequest(BaseModel):
    name: str | None = None
    notes: str | None = None
    meta_yaml: str | None = None
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


class PositionKey(BaseModel):
    account_id: int
    con_id: int


class PositionAssignRequest(BaseModel):
    positions: list[PositionKey] = Field(min_length=1)
    source: str
    created_by: str
    confidence: float | None = None
    reason: str | None = None


class PositionUnassignRequest(BaseModel):
    positions: list[PositionKey] = Field(min_length=1)
    source: str
    created_by: str
    reason: str | None = None


class LiveExecutionAssignRequest(BaseModel):
    ib_exec_ids: list[str] = Field(min_length=1)
    source: str
    created_by: str
    confidence: float | None = None
    reason: str | None = None


class LiveExecutionUnassignRequest(BaseModel):
    ib_exec_ids: list[str] = Field(min_length=1)
    source: str
    created_by: str
    reason: str | None = None


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


def _primary_strategy_subquery():
    """Correlated subquery to get the primary strategy value for a trade group."""
    return (
        select(Tag.value)
        .join(TagLink, TagLink.tag_id == Tag.id)
        .where(
            and_(
                TagLink.entity_type == "trade_groups",
                TagLink.entity_id == TradeGroup.id,
                TagLink.tag_type == "strategy",
                TagLink.is_primary.is_(True),
            )
        )
        .correlate(TradeGroup)
        .scalar_subquery()
        .label("primary_strategy_value")
    )


@router.get("/trade-groups", response_model=list[TradeGroupResponse])
def list_trade_groups(  # noqa: PLR0913
    account_id: int | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    strategy_tag: str | None = Query(default=None),
    theme_tag: str | None = Query(default=None),
    q: str | None = Query(default=None),
    opened_from: datetime | None = Query(default=None),  # noqa: B008
    opened_to: datetime | None = Query(default=None),  # noqa: B008
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = DB_SESSION_DEPENDENCY,
):
    strategy_value_col = _primary_strategy_subquery()
    stmt = select(TradeGroup, strategy_value_col)
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

    if q:
        normalized_q = _normalize_tag_value(q)
        # Escape LIKE metacharacters so %, _, and \ are treated literally
        escaped_q = normalized_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        # Search across group name and primary strategy value
        strategy_name_exists = (
            select(Tag.id)
            .join(TagLink, TagLink.tag_id == Tag.id)
            .where(
                and_(
                    TagLink.entity_type == "trade_groups",
                    TagLink.entity_id == TradeGroup.id,
                    TagLink.tag_type == "strategy",
                    TagLink.is_primary.is_(True),
                    Tag.normalized_value.like(f"%{escaped_q}%", escape="\\"),
                )
            )
            .correlate(TradeGroup)
            .exists()
        )
        stmt = stmt.where(
            or_(
                func.lower(TradeGroup.name).like(f"%{escaped_q}%", escape="\\"),
                strategy_name_exists,
            )
        )

    rows = db.execute(stmt.order_by(TradeGroup.created_at.desc()).limit(limit)).all()
    # Batched settled Total PnL for every group in the page (two queries, no N+1).
    total_pnls = trade_group_total_pnls(db, [trade_group.id for trade_group, _ in rows])
    results = []
    for trade_group, strategy_val in rows:
        resp = TradeGroupResponse.model_validate(trade_group)
        resp.primary_strategy_value = strategy_val
        resp.total_pnl = total_pnls.get(trade_group.id)
        results.append(resp)
    return results


@router.post("/trade-groups", response_model=TradeGroupResponse, status_code=201)
def create_trade_group(body: TradeGroupCreateRequest, db: Session = DB_SESSION_DEPENDENCY):
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    _parse_meta_or_400(body.meta_yaml)  # validate; raises 400 on malformed YAML

    opened_at = body.opened_at or _now_utc()
    trade_group = TradeGroup(
        account_id=None,
        name=body.name,
        notes=body.notes,
        meta_yaml=body.meta_yaml or None,
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
            raise HTTPException(status_code=400, detail="strategy_tag_id must reference a strategy tag")
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
    execution_count = db.execute(select(func.count()).select_from(TradeGroupExecution).where(TradeGroupExecution.trade_group_id == trade_group_id)).scalar_one()

    # Resolve the group's primary strategy value. This is a subquery-computed
    # field (not a column on TradeGroup), so model_validate leaves it None;
    # populate it explicitly so deep links carrying only a trade_group_id can
    # resolve the owning strategy instead of falling back to the first one.
    primary_strategy_value = db.execute(select(_primary_strategy_subquery()).where(TradeGroup.id == trade_group_id)).scalar_one_or_none()

    base = TradeGroupResponse.model_validate(trade_group).model_dump()
    base["primary_strategy_value"] = primary_strategy_value
    return TradeGroupDetailResponse(
        **base,
        tags=[TagLinkResponse.model_validate(row) for row in tag_links],
        execution_count=execution_count,
        meta=_parse_meta_or_400(trade_group.meta_yaml),
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
    if body.meta_yaml is not None:
        _parse_meta_or_400(body.meta_yaml)  # validate; raises 400 on malformed YAML
        # Blank clears the spec; otherwise store the raw source verbatim.
        trade_group.meta_yaml = body.meta_yaml or None
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
    assignments = db.execute(select(TradeGroupExecution).where(TradeGroupExecution.trade_group_id == trade_group_id)).scalars().all()

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

    db.query(TagLink).filter(TagLink.entity_type == "trade_groups", TagLink.entity_id == trade_group_id).delete()
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
    # Intentional: trade-group membership is cross-account in V1.
    # Do not require TradeGroup.account_id to match TradeExecution.account_id.
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    trade_group = _ensure_group(db, trade_group_id)
    executions = db.execute(select(TradeExecution).where(TradeExecution.id.in_(body.execution_ids))).scalars().all()
    if len(executions) != len(set(body.execution_ids)):
        raise HTTPException(status_code=404, detail="One or more executions not found")

    # Auto-populate account_id from the first assigned execution when not yet set.
    if trade_group.account_id is None and executions:
        trade_group.account_id = executions[0].account_id
        trade_group.updated_at = _now_utc()

    for execution in executions:
        existing = db.execute(select(TradeGroupExecution).where(TradeGroupExecution.trade_execution_id == execution.id)).scalar_one_or_none()
        if existing and existing.trade_group_id == trade_group_id:
            continue
        if existing and not body.force_reassign:
            raise HTTPException(status_code=409, detail=f"Execution {execution.id} already assigned")

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
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))


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
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))


def _upsert_settled_execution_link(  # noqa: PLR0913
    db: Session,
    *,
    trade_execution_id: int,
    trade_group_id: int,
    source: str,
    created_by: str,
    confidence: float | None,
    reason: str | None,
) -> None:
    """Assign (or move) a settled execution to a group, idempotently.

    Mirrors ``assign_executions`` but never raises on an existing assignment —
    a fan-out from a position should just move the fill to the target group.
    """
    existing = db.execute(select(TradeGroupExecution).where(TradeGroupExecution.trade_execution_id == trade_execution_id)).scalar_one_or_none()
    if existing is not None and existing.trade_group_id == trade_group_id:
        return
    if existing is not None:
        previous_group_id = existing.trade_group_id
        existing.trade_group_id = trade_group_id
        existing.source = source
        existing.created_by = created_by
        existing.confidence = confidence
        existing.assigned_at = _now_utc()
        event_type = "reassigned"
    else:
        db.add(
            TradeGroupExecution(
                trade_group_id=trade_group_id,
                trade_execution_id=trade_execution_id,
                source=source,
                created_by=created_by,
                confidence=confidence,
                assigned_at=_now_utc(),
            )
        )
        previous_group_id = None
        event_type = "assigned"
    db.add(
        TradeGroupExecutionEvent(
            trade_execution_id=trade_execution_id,
            from_trade_group_id=previous_group_id,
            to_trade_group_id=trade_group_id,
            event_type=event_type,
            source=source,
            created_by=created_by,
            confidence=confidence,
            reason=reason,
            event_at=_now_utc(),
        )
    )


@router.post("/trade-groups/{trade_group_id}/positions:assign", status_code=204)
def assign_positions(
    trade_group_id: int,
    body: PositionAssignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Assign a whole position (by account_id + con_id) to a group.

    A position is just a rollup of fills, so this fans out to the position's
    constituent *executions* — uniform with FlexQuery — rather than tagging the
    net instrument. Two execution layers are covered:
      - settled fills (``TradeExecution``) -> ``TradeGroupExecution``;
      - live, not-yet-settled fills (``LiveExecution``) -> ``TradeGroupLiveExecution``,
        keyed by ib_exec_id so a real-time TWS position can be grouped immediately.
    For partial (per-fill) assignment, use the per-execution tagging flow.
    """
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    trade_group = _ensure_group(db, trade_group_id)

    # Auto-populate account_id from the first assigned position when not yet set.
    if trade_group.account_id is None and body.positions:
        trade_group.account_id = body.positions[0].account_id
        trade_group.updated_at = _now_utc()

    for pos in body.positions:
        settled = (
            db.execute(
                select(TradeExecution.id).where(
                    and_(
                        TradeExecution.account_id == pos.account_id,
                        TradeExecution.con_id == pos.con_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for execution_id in settled:
            _upsert_settled_execution_link(
                db,
                trade_execution_id=execution_id,
                trade_group_id=trade_group_id,
                source=body.source,
                created_by=body.created_by,
                confidence=body.confidence,
                reason=body.reason,
            )

        live = (
            db.execute(
                select(LiveExecution).where(
                    and_(
                        LiveExecution.account_id == pos.account_id,
                        LiveExecution.con_id == pos.con_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for live_exec in live:
            existing = db.execute(select(TradeGroupLiveExecution).where(TradeGroupLiveExecution.ib_exec_id == live_exec.ib_exec_id)).scalar_one_or_none()
            if existing is not None:
                existing.trade_group_id = trade_group_id
                existing.account_id = live_exec.account_id
                existing.con_id = live_exec.con_id
                existing.source = body.source
                existing.created_by = body.created_by
                existing.confidence = body.confidence
                existing.assigned_at = _now_utc()
            else:
                db.add(
                    TradeGroupLiveExecution(
                        trade_group_id=trade_group_id,
                        ib_exec_id=live_exec.ib_exec_id,
                        account_id=live_exec.account_id,
                        con_id=live_exec.con_id,
                        source=body.source,
                        created_by=body.created_by,
                        confidence=body.confidence,
                        assigned_at=_now_utc(),
                    )
                )

    db.commit()
    broadcaster.publish(make_coarse_event(TOPIC_POSITIONS, "positions.changed"))
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))


@router.post("/trade-groups/{trade_group_id}/positions:unassign", status_code=204)
def unassign_positions(
    trade_group_id: int,
    body: PositionUnassignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Remove a whole position from a group by unassigning all its fills."""
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    _ensure_group(db, trade_group_id)
    for pos in body.positions:
        settled_links = (
            db.execute(
                select(TradeGroupExecution)
                .join(
                    TradeExecution,
                    TradeExecution.id == TradeGroupExecution.trade_execution_id,
                )
                .where(
                    and_(
                        TradeGroupExecution.trade_group_id == trade_group_id,
                        TradeExecution.account_id == pos.account_id,
                        TradeExecution.con_id == pos.con_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for link in settled_links:
            db.add(
                TradeGroupExecutionEvent(
                    trade_execution_id=link.trade_execution_id,
                    from_trade_group_id=trade_group_id,
                    to_trade_group_id=None,
                    event_type="unassigned",
                    source=body.source,
                    created_by=body.created_by,
                    reason=body.reason,
                    event_at=_now_utc(),
                )
            )
            db.delete(link)

        live_links = (
            db.execute(
                select(TradeGroupLiveExecution).where(
                    and_(
                        TradeGroupLiveExecution.trade_group_id == trade_group_id,
                        TradeGroupLiveExecution.account_id == pos.account_id,
                        TradeGroupLiveExecution.con_id == pos.con_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        for link in live_links:
            db.delete(link)

    db.commit()
    broadcaster.publish(make_coarse_event(TOPIC_POSITIONS, "positions.changed"))
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))


def _live_combo_siblings(db: Session, live_execs: Iterable[LiveExecution]) -> dict[str, LiveExecution]:
    """Every other live fill belonging to the same combo order(s).

    A combo is tagged as a unit: naming any one of its fills pulls in the BAG
    summary and all legs. This matters beyond tidiness — position attribution is
    keyed by ``con_id``, and the BAG summary carries a placeholder conId that
    matches no position, so tagging the summary alone would attribute nothing.

    Returns ``{ib_exec_id: LiveExecution}`` for the siblings only (the inputs are
    not re-included). Empty when none of the inputs belong to a combo.
    """
    perm_ids = {le.ib_perm_id for le in live_execs if le.exec_role in {"combo_summary", "leg"} and le.ib_perm_id}
    order_ids = {le.ib_order_id for le in live_execs if le.exec_role in {"combo_summary", "leg"} and not le.ib_perm_id and le.ib_order_id}
    if not perm_ids and not order_ids:
        return {}

    clauses = []
    if perm_ids:
        clauses.append(LiveExecution.ib_perm_id.in_(perm_ids))
    if order_ids:
        clauses.append(and_(LiveExecution.ib_perm_id.is_(None), LiveExecution.ib_order_id.in_(order_ids)))
    named = {le.ib_exec_id for le in live_execs}
    siblings = db.execute(select(LiveExecution).where(or_(*clauses))).scalars().all()
    return {le.ib_exec_id: le for le in siblings if le.ib_exec_id not in named}


@router.post("/trade-groups/{trade_group_id}/live-executions:assign", status_code=204)
def assign_live_executions(
    trade_group_id: int,
    body: LiveExecutionAssignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Preemptively tag unsettled TWS fills (by ib_exec_id) to a group.

    Lets the desk assign a live fill to a trade group before it settles into
    ``trade_executions``. The link is keyed by ``ib_exec_id``; when FlexQuery (or
    the intraday purge) settles the fill, the carry-over folds it into the
    canonical ``TradeGroupExecution``. One group per live fill — assigning a fill
    already tagged elsewhere moves it here.
    """
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    trade_group = _ensure_group(db, trade_group_id)
    live_by_exec_id = {le.ib_exec_id: le for le in db.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.in_(body.ib_exec_ids))).scalars().all()}
    missing = [eid for eid in body.ib_exec_ids if eid not in live_by_exec_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown live execution(s): {', '.join(missing)}")
    live_by_exec_id.update(_live_combo_siblings(db, live_by_exec_id.values()))

    if trade_group.account_id is None and live_by_exec_id:
        trade_group.account_id = next(iter(live_by_exec_id.values())).account_id
        trade_group.updated_at = _now_utc()

    for ib_exec_id, live_exec in live_by_exec_id.items():
        existing = db.execute(select(TradeGroupLiveExecution).where(TradeGroupLiveExecution.ib_exec_id == ib_exec_id)).scalar_one_or_none()
        if existing is not None:
            existing.trade_group_id = trade_group_id
            existing.account_id = live_exec.account_id
            existing.con_id = live_exec.con_id
            existing.source = body.source
            existing.created_by = body.created_by
            existing.confidence = body.confidence
            existing.assigned_at = _now_utc()
        else:
            db.add(
                TradeGroupLiveExecution(
                    trade_group_id=trade_group_id,
                    ib_exec_id=ib_exec_id,
                    account_id=live_exec.account_id,
                    con_id=live_exec.con_id,
                    source=body.source,
                    created_by=body.created_by,
                    confidence=body.confidence,
                    assigned_at=_now_utc(),
                )
            )

    db.commit()
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))
    broadcaster.publish(make_coarse_event(TOPIC_POSITIONS, "positions.changed"))


@router.post("/trade-groups/{trade_group_id}/live-executions:unassign", status_code=204)
def unassign_live_executions(
    trade_group_id: int,
    body: LiveExecutionUnassignRequest,
    db: Session = DB_SESSION_DEPENDENCY,
):
    """Remove preemptive live-fill tags (by ib_exec_id) from a group."""
    if body.source not in ASSIGNMENT_SOURCES:
        raise HTTPException(status_code=400, detail="Invalid source")

    _ensure_group(db, trade_group_id)
    # Unassign the whole combo when any of its fills is named, mirroring assign.
    named = db.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.in_(body.ib_exec_ids))).scalars().all()
    exec_ids = set(body.ib_exec_ids) | set(_live_combo_siblings(db, named))
    links = (
        db.execute(
            select(TradeGroupLiveExecution).where(
                and_(
                    TradeGroupLiveExecution.trade_group_id == trade_group_id,
                    TradeGroupLiveExecution.ib_exec_id.in_(exec_ids),
                )
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        db.delete(link)

    db.commit()
    broadcaster.publish(make_coarse_event(TOPIC_TRADES, "trades.changed"))
    broadcaster.publish(make_coarse_event(TOPIC_POSITIONS, "positions.changed"))


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
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
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
            event_type = "execution_reassigned_in" if row.to_trade_group_id == trade_group_id else "execution_reassigned_out"
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
                related_trade_group_id=row.from_trade_group_id if row.to_trade_group_id == trade_group_id else row.to_trade_group_id,
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
        related_id = link.parent_trade_group_id if link.child_trade_group_id == trade_group_id else link.child_trade_group_id
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


class TradeGroupExecutionItem(BaseModel):
    id: int
    trade_id: int | None
    account_id: int
    account_alias: str | None
    executed_at: datetime
    side: str | None
    quantity: float
    price: float
    commission: float | None
    realized_pnl: float | None
    exec_role: str
    sec_type: str | None
    contract_display: str | None
    data_source: str
    # IBKR FlexQuery trade codes (the `notes` attribute): A=assigned,
    # Ep=from expiration, Ex=exercise, P=partial, WS=wash sale, etc. Null for
    # TWS/live-sourced rows.
    ib_codes: str | None = None
    # False for preemptively-tagged live fills not yet settled.
    settled: bool = True
    ib_exec_id: str | None = None


class TradeGroupOpenPositionItem(BaseModel):
    account_id: int
    account_alias: str | None
    con_id: int
    symbol: str | None
    local_symbol: str | None
    contract_display: str | None
    sec_type: str | None
    # Option contract detail (null for non-options / no settled snapshot yet),
    # mirroring the Positions table's columns.
    right: str | None = None
    option_expiry_date: str | None = None
    dte: int | None = None
    strike: float | None = None
    position: float
    avg_cost: float
    multiplier: str | None
    mark_price: float | None
    position_value: float | None
    fifo_pnl_unrealized: float | None
    as_of_date: date | None
    # Intraday overlay (additive): live current-state fields.
    source: str = "settled"  # "live" | "settled"
    mark: float | None = None
    mark_ts: datetime | None = None
    live_unrealized: float | None = None
    # Staleness of the live TWS overlay — see ``is_live_stale``. True when the
    # live snapshot is from a prior Mountain-Time calendar day and a settled
    # FlexQuery import exists to fall back to. The frontend uses this to render
    # the freshness badge as "stale" (not green "live") and to blank the live
    # overlay columns.
    live_fetched_at: datetime | None = None
    live_is_stale: bool = False
    # Live option metrics (additive; from the separate option-metrics sync job).
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    und_price: float | None = None
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None


class TradeGroupAccountPnl(BaseModel):
    """Per-account rollup of a group's P&L. Sums reconcile to the group totals."""

    account_id: int
    account_alias: str | None
    realized_pnl: float | None
    unrealized_pnl: float | None  # settled
    intraday_unrealized_pnl: float | None = None
    intraday_realized_pnl: float | None = None
    intraday_total_pnl: float | None = None


class TradeGroupExecutionsResponse(BaseModel):
    trade_group_id: int
    total_realized_pnl: float | None
    total_unrealized_pnl: float | None
    executions: list[TradeGroupExecutionItem]
    open_positions: list[TradeGroupOpenPositionItem]
    # Intraday overlay (additive): settled fields above stay unchanged.
    intraday_unrealized_pnl: float | None = None
    intraday_realized_pnl: float | None = None
    intraday_total_pnl: float | None = None
    marks_as_of: datetime | None = None
    # Per-account breakdown (additive): empty when the group has no executions.
    by_account: list[TradeGroupAccountPnl] = []


class _AccountOverlay(BaseModel):
    unrealized: float | None
    intraday_unrealized: float | None
    intraday_realized: float | None
    intraday_total: float | None


class _OpenPositionsOverlay(BaseModel):
    open_positions: list[TradeGroupOpenPositionItem]
    total_unrealized: float | None
    intraday_unrealized: float | None
    intraday_realized: float | None
    intraday_total: float | None
    marks_as_of: datetime | None
    by_account: dict[int, _AccountOverlay] = {}


def _combine_intraday(unrealized: float | None, realized: float | None) -> float | None:
    if unrealized is None and realized is None:
        return None
    return (unrealized or 0.0) + (realized or 0.0)


def _build_open_positions_overlay(
    db: Session,
    account_con_pairs: set[tuple[int, int]],
    settled_exec_ids: set[str],
    total_pnl: float | None,
    realized_by_account: dict[int, float | None] | None = None,
) -> _OpenPositionsOverlay:
    """Merge the live TWS overlay onto the settled snapshot for a group's pairs.

    Settled totals stay backward-compatible; intraday fields are additive.
    """
    empty = _OpenPositionsOverlay(
        open_positions=[],
        total_unrealized=None,
        intraday_unrealized=None,
        intraday_realized=None,
        intraday_total=None,
        marks_as_of=None,
    )
    if not account_con_pairs:
        return empty

    flex_rows, live_rows, quotes, live_execs = load_overlay_inputs(db, account_con_pairs)
    # Price magnifiers normalize cents-quoted marks (e.g. grain futures) into the
    # multiplier's dollar unit before merge_positions computes live PnL.
    overlay_con_ids = {p.con_id for p in flex_rows} | {p.con_id for p in live_rows}
    magnifiers: dict[int, int] = {}
    metrics: dict[int, LatestOptionMetrics] = {}
    if overlay_con_ids:
        magnifiers = dict(db.execute(select(ContractRef.con_id, ContractRef.price_magnifier).where(ContractRef.con_id.in_(list(overlay_con_ids)))).all())
        metrics = {m.con_id: m for m in db.execute(select(LatestOptionMetrics).where(LatestOptionMetrics.con_id.in_(list(overlay_con_ids)))).scalars().all()}
    views = merge_positions(flex_rows, live_rows, quotes, magnifiers, metrics)

    view_account_ids = {v.account_id for v in views}
    alias_by_id = {}
    if view_account_ids:
        alias_by_id = {a.id: a for a in db.execute(select(Account).where(Account.id.in_(list(view_account_ids)))).scalars().all()}
    flex_by_key = {(p.account_id, p.con_id): p for p in flex_rows}
    live_fetched_by_key = {(p.account_id, p.con_id): p.fetched_at for p in live_rows}

    open_positions = [
        _view_to_open_position(
            view,
            flex_by_key.get((view.account_id, view.con_id)),
            alias_by_id.get(view.account_id),
            live_fetched_by_key.get((view.account_id, view.con_id)),
        )
        for view in views
    ]

    # Single source for the group totals (shared with the trade_group_pnl tool).
    totals = overlay_totals(flex_rows, views, live_execs, settled_exec_ids, total_pnl)

    # Per-account breakdown using the same partitioning as the totals above, so
    # the per-account values reconcile to the group totals.
    realized_by_account = realized_by_account or {}
    views_by_account: dict[int, list] = {}
    for view in views:
        views_by_account.setdefault(view.account_id, []).append(view)
    live_execs_by_account: dict[int, list] = {}
    for ex in live_execs:
        live_execs_by_account.setdefault(ex.account_id, []).append(ex)

    by_account: dict[int, _AccountOverlay] = {}
    for acct_id in set(views_by_account) | set(realized_by_account):
        acct_views = views_by_account.get(acct_id, [])
        acct_settled = [v.settled_unrealized for v in acct_views if v.settled_unrealized is not None]
        acct_unrealized = sum(acct_settled) if acct_settled else None
        acct_intraday_unrealized = intraday_unrealized_total(acct_views)
        acct_realized = realized_by_account.get(acct_id)
        _, acct_live_realized = dedupe_live_realized(settled_exec_ids, live_execs_by_account.get(acct_id, []))
        acct_intraday_realized = (acct_realized or 0.0) + acct_live_realized if (acct_realized is not None or acct_live_realized) else None
        by_account[acct_id] = _AccountOverlay(
            unrealized=acct_unrealized,
            intraday_unrealized=acct_intraday_unrealized,
            intraday_realized=acct_intraday_realized,
            intraday_total=_combine_intraday(acct_intraday_unrealized, acct_intraday_realized),
        )

    return _OpenPositionsOverlay(
        open_positions=open_positions,
        total_unrealized=totals.settled_unrealized,
        intraday_unrealized=totals.intraday_unrealized,
        intraday_realized=totals.intraday_realized,
        intraday_total=totals.intraday_total,
        marks_as_of=totals.marks_as_of,
        by_account=by_account,
    )


def _view_to_open_position(view, flex, account, live_fetched_at) -> TradeGroupOpenPositionItem:
    """Map a unified PositionView to the response item (settled fields kept additive)."""
    # Build the Contract label exactly like the Positions table does: off the
    # settled snapshot row when there is one (its symbol/local_symbol carry the
    # OSI form and the expiry), falling back to the unified view for positions
    # opened today that have no snapshot yet.
    display_symbol = (flex.symbol if flex else None) or view.symbol
    display_local_symbol = (flex.local_symbol if flex else None) or view.local_symbol
    display_sec_type = (flex.sec_type if flex else None) or view.sec_type
    display_right = (flex.right if flex else None) or view.right
    display_strike = (flex.strike if flex else None) if flex and flex.strike is not None else view.strike
    inferred_month = infer_contract_month_from_local_symbol(
        local_symbol=display_local_symbol,
        contract_expiry=flex.last_trade_date if flex else None,
        sec_type=display_sec_type,
    )
    display_name = contract_display_name(
        symbol=display_symbol,
        sec_type=display_sec_type,
        local_symbol=display_local_symbol,
        right=display_right,
        strike=display_strike,
        contract_expiry=flex.last_trade_date if flex else None,
        contract_month=inferred_month,
        exchange=flex.exchange if flex else None,
        trading_class=flex.trading_class if flex else None,
    )
    # Expiry/DTE come off the settled snapshot's last_trade_date; a live-only
    # row (opened today, no snapshot) has no expiry to derive from.
    option_expiry_date, dte = _derive_option_expiry_and_dte(flex) if flex else (None, None)
    return TradeGroupOpenPositionItem(
        account_id=view.account_id,
        account_alias=(account.alias if account else None) or (account.account if account else None),
        con_id=view.con_id,
        symbol=view.symbol,
        local_symbol=view.local_symbol,
        contract_display=display_name,
        sec_type=view.sec_type,
        right=display_right,
        option_expiry_date=option_expiry_date,
        dte=dte,
        strike=display_strike,
        position=view.position,
        avg_cost=view.avg_cost,
        multiplier=view.multiplier,
        mark_price=view.settled_mark_price,
        position_value=view.settled_position_value,
        fifo_pnl_unrealized=view.settled_unrealized,
        as_of_date=view.as_of_date,
        source=view.source,
        mark=view.mark,
        mark_ts=view.mark_ts,
        live_unrealized=view.live_unrealized,
        live_fetched_at=live_fetched_at,
        # Stale when the live snapshot is from a prior MT day and the settled
        # snapshot exists to fall back to (see ``is_live_stale``).
        live_is_stale=is_live_stale(live_fetched_at, flex.fetched_at if flex else None),
        iv=view.iv,
        delta=view.delta,
        gamma=view.gamma,
        theta=view.theta,
        vega=view.vega,
        und_price=view.und_price,
        intrinsic_value=view.intrinsic_value,
        extrinsic_value=view.extrinsic_value,
    )


@router.get(
    "/trade-groups/{trade_group_id}/executions",
    response_model=TradeGroupExecutionsResponse,
)
def trade_group_executions(trade_group_id: int, db: Session = DB_SESSION_DEPENDENCY):
    _ensure_group(db, trade_group_id)

    rows = db.execute(
        select(TradeExecution, ContractRef, Trade, Account)
        .join(
            TradeGroupExecution,
            TradeGroupExecution.trade_execution_id == TradeExecution.id,
        )
        .join(Trade, Trade.id == TradeExecution.trade_id)
        .outerjoin(ContractRef, ContractRef.con_id == TradeExecution.con_id)
        .outerjoin(Account, Account.id == TradeExecution.account_id)
        .where(TradeGroupExecution.trade_group_id == trade_group_id)
        .order_by(TradeExecution.executed_at.asc(), TradeExecution.id.asc())
    ).all()

    items: list[TradeGroupExecutionItem] = []
    rows_by_account: dict[int, list[tuple]] = {}
    alias_by_account: dict[int, str | None] = {}
    for row in rows:
        execution, contract_ref, _trade, account = row
        rows_by_account.setdefault(execution.account_id, []).append(row)
        alias_by_account.setdefault(execution.account_id, account.alias if account else None)
        items.append(
            TradeGroupExecutionItem(
                id=execution.id,
                trade_id=execution.trade_id,
                account_id=execution.account_id,
                account_alias=account.alias if account else None,
                executed_at=execution.executed_at,
                side=execution.side,
                quantity=execution.quantity,
                price=execution.price,
                commission=execution.commission,
                realized_pnl=_execution_realized_pnl(execution.raw),
                exec_role=execution.exec_role,
                sec_type=execution.sec_type,
                contract_display=_contract_display_from_raw(execution.raw, contract_ref),
                data_source=execution.data_source,
                ib_codes=_execution_ib_codes(execution.raw),
                settled=True,
                ib_exec_id=execution.ib_exec_id,
            )
        )

    # Preemptively-tagged unsettled live fills assigned to this group (keyed by
    # ib_exec_id). Excluded once settled — by then the carry-over has folded them
    # into trade_group_executions and they appear as settled rows above.
    live_rows = db.execute(
        select(LiveExecution, Account)
        .join(TradeGroupLiveExecution, TradeGroupLiveExecution.ib_exec_id == LiveExecution.ib_exec_id)
        .outerjoin(Account, Account.id == LiveExecution.account_id)
        .where(
            TradeGroupLiveExecution.trade_group_id == trade_group_id,
            LiveExecution.ib_exec_id.not_in(select(TradeExecution.ib_exec_id)),
        )
        .order_by(LiveExecution.exec_time.asc(), LiveExecution.id.asc())
    ).all()
    for live_exec, account in live_rows:
        items.append(
            TradeGroupExecutionItem(
                id=-live_exec.id,
                trade_id=None,
                account_id=live_exec.account_id,
                account_alias=account.alias if account else None,
                executed_at=live_exec.exec_time,
                side=live_exec.side,
                quantity=live_exec.quantity,
                price=live_exec.price,
                commission=None,
                realized_pnl=live_exec.realized_pnl,
                exec_role=live_exec.exec_role,
                sec_type=live_exec.sec_type,
                contract_display=contract_display_name(
                    symbol=live_exec.symbol,
                    sec_type=live_exec.sec_type,
                    local_symbol=live_exec.local_symbol,
                    right=live_exec.right,
                    strike=live_exec.strike,
                    contract_expiry=None,
                    contract_month=None,
                    exchange=None,
                    trading_class=None,
                ),
                data_source="tws-live",
                settled=False,
                ib_exec_id=live_exec.ib_exec_id,
            )
        )

    # Realized total via the shared combo-aware helper (also used by the
    # trade_group_pnl tool, so the figures cannot diverge). The same helper runs
    # per account partition so the per-account totals reconcile to the group.
    total_pnl = trade_group_realized_pnl([execution for execution, _ref, _trade, _account in rows])
    realized_by_account = {acct_id: trade_group_realized_pnl([execution for execution, *_ in acct_rows]) for acct_id, acct_rows in rows_by_account.items()}

    # Open positions linked to this group: match on (account_id, con_id) pairs
    # that appear in any of the group's executions. The settled snapshot
    # (FlexQuery `positions`) is the base; the live TWS overlay (`live_positions`
    # + `latest_quote` + `live_executions`) is merged on top at read time.
    account_con_pairs = {(execution.account_id, execution.con_id) for execution, _ref, _trade, _account in rows if execution.con_id is not None}
    # Also surface positions whose only link to this group is a tagged *unsettled*
    # live fill (a strike opened today, not yet in trade_executions). Without this,
    # a freshly-opened position stays hidden from Open Positions until it settles.
    account_con_pairs |= {(le.account_id, le.con_id) for le, _account in live_rows if le.con_id is not None}
    settled_exec_ids = {execution.ib_exec_id for execution, _ref, _trade, _account in rows if execution.ib_exec_id}
    overlay = _build_open_positions_overlay(db, account_con_pairs, settled_exec_ids, total_pnl, realized_by_account)

    # Assemble the per-account breakdown over the union of accounts that have
    # realized PnL (from executions) and/or open positions (from the overlay).
    by_account = [
        TradeGroupAccountPnl(
            account_id=acct_id,
            account_alias=alias_by_account.get(acct_id),
            realized_pnl=realized_by_account.get(acct_id),
            unrealized_pnl=(ov.unrealized if (ov := overlay.by_account.get(acct_id)) else None),
            intraday_unrealized_pnl=(ov.intraday_unrealized if ov else None),
            intraday_realized_pnl=(ov.intraday_realized if ov else None),
            intraday_total_pnl=(ov.intraday_total if ov else None),
        )
        for acct_id in sorted(set(realized_by_account) | set(overlay.by_account))
    ]

    return TradeGroupExecutionsResponse(
        trade_group_id=trade_group_id,
        total_realized_pnl=total_pnl,
        total_unrealized_pnl=overlay.total_unrealized,
        executions=items,
        open_positions=overlay.open_positions,
        intraday_unrealized_pnl=overlay.intraday_unrealized,
        intraday_realized_pnl=overlay.intraday_realized,
        intraday_total_pnl=overlay.intraday_total,
        marks_as_of=overlay.marks_as_of,
        by_account=by_account,
    )
