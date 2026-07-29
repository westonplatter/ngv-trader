"""Settle-handoff carry-over for trade-group assignments.

A TWS fill can be tagged to a trade group while still unsettled, via
``TradeGroupLiveExecution`` (keyed by the stable ``ib_exec_id``). When the fill
later settles into ``trade_executions`` — through either the FlexQuery trade sync
or the intraday overlay's purge — that provisional link must transition onto the
canonical ``TradeGroupExecution`` (keyed by the settled row's id) so grouping
survives the live→settled handoff with no gap and no double-count.

This module holds the single, source-agnostic implementation so both sync paths
share identical behavior.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import TradeExecution, TradeGroupExecution, TradeGroupLiveExecution


def carry_over_settled_group_links(session: Session, settled_ids: set[str] | None = None) -> int:
    """Fold live group links onto their now-settled executions; drop the live link.

    ``settled_ids`` optionally scopes the work to a known set of ``ib_exec_id``s
    (e.g. the ids a sync just settled). When omitted, every live link whose
    ``ib_exec_id`` already exists in ``trade_executions`` is reconciled — the
    robust default for the FlexQuery path, which doesn't otherwise track which
    fills settled this run. Returns the count of links carried over.
    """
    stmt = select(TradeGroupLiveExecution)
    if settled_ids is not None:
        if not settled_ids:
            return 0
        stmt = stmt.where(TradeGroupLiveExecution.ib_exec_id.in_(settled_ids))
    links = session.execute(stmt).scalars().all()
    if not links:
        return 0

    exec_id_by_ib = dict(
        session.execute(select(TradeExecution.ib_exec_id, TradeExecution.id).where(TradeExecution.ib_exec_id.in_([link.ib_exec_id for link in links]))).all()
    )

    carried = 0
    for link in links:
        trade_execution_id = exec_id_by_ib.get(link.ib_exec_id)
        if trade_execution_id is None:
            # Not yet settled — leave the live link in place for a later run.
            continue
        if _apply_carry(session, link, trade_execution_id):
            carried += 1
    return carried


def carry_over_link_to_execution(session: Session, live_ib_exec_id: str, trade_execution_id: int) -> int:
    """Fold one live group link onto an explicitly-identified settled execution.

    For settle-handoff cases where the live and settled rows carry DIFFERENT
    ``ib_exec_id``s — combo-leg id normalization and expiration/assignment book
    events — the id-equality path in ``carry_over_settled_group_links`` cannot
    see them, so the caller supplies the resolved ``trade_execution_id`` directly.
    Returns 1 if a new ``TradeGroupExecution`` was created, else 0. A no-op (0)
    when the live fill was never tagged.
    """
    link = session.execute(select(TradeGroupLiveExecution).where(TradeGroupLiveExecution.ib_exec_id == live_ib_exec_id)).scalar_one_or_none()
    if link is None:
        return 0
    return 1 if _apply_carry(session, link, trade_execution_id) else 0


def _apply_carry(session: Session, link: TradeGroupLiveExecution, trade_execution_id: int) -> bool:
    """Create the canonical group link (unless one exists) and drop the live link.

    Returns whether a new ``TradeGroupExecution`` was inserted. The live link is
    always deleted so the handoff leaves no duplicate, matching the original
    behavior for the id-equality path.
    """
    already = session.execute(select(TradeGroupExecution).where(TradeGroupExecution.trade_execution_id == trade_execution_id)).scalar_one_or_none()
    inserted = False
    if already is None:
        session.add(
            TradeGroupExecution(
                trade_group_id=link.trade_group_id,
                trade_execution_id=trade_execution_id,
                source=link.source,
                created_by=link.created_by,
                confidence=link.confidence,
                assigned_at=link.assigned_at,
            )
        )
        inserted = True
    session.delete(link)
    return inserted
