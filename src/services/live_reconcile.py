"""Reconcile orphaned live executions against settled ``trade_executions``.

The intraday TWS feed and the FlexQuery settled feed sometimes book the SAME
economic fill under DIFFERENT ``ib_exec_id``s. The exact-id purge in
``intraday_sync_tws._purge_settled`` matches only on id equality, so those rows
are never cleared and linger as phantom "unsettled" fills. Beyond the cosmetic
badge, they corrupt realized P&L: the intraday overlay loads live fills by
``(account_id, con_id)`` and adds their ``realized_pnl`` on top of the settled
total unless the id is already settled (``intraday_overlay.dedupe_live_realized``),
so an orphan whose settled twin carries the same realized is double-counted.

Two id-divergence patterns are reconciled here:

  A. **Combo-leg id normalization.** A real-time combo leg carries an extra
     trailing leg-index segment vs FlexQuery — e.g. live ``…6a3d2811.03.01.01``
     vs settled ``…6a3d2811.03.01``. Stripping the live id's final segment
     yields the settled id exactly; this is a precise, non-heuristic match. This
     is the class that produced the only observed dollar double-count.

  B. **Expiration / assignment / exercise book events.** The position leaves the
     account with no real fill: the live feed emits a synthetic fill (an expired
     option books at price 0; an assignment-delivered underlying books at the
     settlement price) while FlexQuery books a ``FLEX-TX-…`` row carrying an
     ``Ep``/``A``/``Ex`` note. The two share no id, so we match on
     ``(account_id, con_id, |quantity|, side, price, trade date)`` scoped to a
     settled *book event* — bounded because a position can expire/assign/exercise
     at most once per contract per day, and the price must agree.

A third pattern is not an id divergence at all but a redundant row:

  C. **BAG combo summaries.** The intraday feed delivers a combo as one BAG
     summary fill plus one fill per leg. FlexQuery does not persist the broker's
     BAG fill — it *synthesizes its own* combo summary off a leg's exec id, with
     ``con_id``/``symbol`` NULL — so the live BAG row (on placeholder
     ``con_id`` 28812380) shares no id, contract or order key with anything
     settled. Rather than match it, we establish that its combo settled and drop
     it as pure display redundancy: purge once no live *leg* shares its order
     key (every leg has already reconciled out) *and* settled legs exist at its
     timestamp. Its group tag fans out onto those settled legs first. A combo
     filling in partials emits one summary per partial under a shared order key,
     so peer summaries are not counted — see ``_has_live_siblings``.

When a match is found, any preemptive trade-group tag on the live fill is
carried onto the settled execution(s) before the live row is deleted, so
grouping survives the handoff with no gap and no double-count.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.models import LiveExecution, TradeExecution
from src.services.group_link_carryover import (
    carry_over_link_to_execution,
    carry_over_link_to_executions,
)

logger = logging.getLogger(__name__)

# Live TWS side strings normalize to FlexQuery's BUY/SELL for cross-feed matching.
_LIVE_SIDE_NORMALIZATION = {"BOT": "BUY", "SLD": "SELL", "BUY": "BUY", "SELL": "SELL"}

# IBKR Flex notes codes that mark a book event (no real fill behind the row):
# Ep=expired, A=assigned, Ex=exercised. Tokenize before matching so "AFx"/"IA"
# are not misread as an "A". Kept self-contained here rather than importing a
# sync-path internal, so this reconciliation is insulated from that code's churn.
_NOTES_SPLIT = re.compile(r"[;,\s]+")
_BOOK_NOTE_CODES = frozenset({"EP", "A", "EX"})

# Prices are compared with a tolerance rather than exact float equality.
_PRICE_EPS = 1e-6
_QTY_EPS = 1e-9


def _normalize_live_side(side: str | None) -> str | None:
    if side is None:
        return None
    return _LIVE_SIDE_NORMALIZATION.get(side.strip().upper())


def _strip_last_segment(ib_exec_id: str) -> str | None:
    """Return the id minus its final ``.<segment>``, or None if there is none."""
    dot = ib_exec_id.rfind(".")
    if dot <= 0:
        return None
    return ib_exec_id[:dot]


def _same_contract_fill(live: LiveExecution, settled: TradeExecution) -> bool:
    """Sanity guard: the two rows describe the same contract/qty/side."""
    return (
        live.con_id is not None
        and live.con_id == settled.con_id
        and abs(abs(live.quantity) - abs(settled.quantity)) <= _QTY_EPS
        and _normalize_live_side(live.side) == (settled.side or "").strip().upper()
    )


def _has_book_note(raw: Any) -> bool:
    """True when the raw Flex ``notes`` carry an Ep/A/Ex book-event code."""
    if not isinstance(raw, dict):
        return False
    notes = raw.get("notes")
    if not notes:
        return False
    codes = {tok.upper() for tok in _NOTES_SPLIT.split(str(notes)) if tok}
    return bool(codes & _BOOK_NOTE_CODES)


def _is_book_event(settled: TradeExecution) -> bool:
    """A FlexQuery expiration/assignment/exercise row (no real fill behind it)."""
    return settled.ib_exec_id.startswith("FLEX-TX-") or _has_book_note(settled.raw)


def _match_leg_strip(session: Session, live: LiveExecution) -> TradeExecution | None:
    """Class A: settled id equals the live id with its trailing leg segment removed."""
    stripped = _strip_last_segment(live.ib_exec_id)
    if stripped is None:
        return None
    settled = session.execute(select(TradeExecution).where(TradeExecution.ib_exec_id == stripped)).scalar_one_or_none()
    if settled is not None and _same_contract_fill(live, settled):
        return settled
    return None


def _match_book_event(session: Session, live: LiveExecution) -> TradeExecution | None:
    """Class B: a settled book event on the same contract, day, qty, side and price.

    Handles both an expired option (live price 0) and an assignment-delivered
    underlying (live price = settlement price); the settled book event's price
    must agree either way, which keeps the match from pairing an unrelated real
    fill on the same contract with a book event.
    """
    if live.con_id is None:
        return None
    live_side = _normalize_live_side(live.side)
    live_day = live.exec_time.date()
    candidates = (
        session.execute(
            select(TradeExecution).where(
                TradeExecution.account_id == live.account_id,
                TradeExecution.con_id == live.con_id,
            )
        )
        .scalars()
        .all()
    )
    for settled in candidates:
        if not _is_book_event(settled):
            continue
        if abs(abs(settled.quantity) - abs(live.quantity)) > _QTY_EPS:
            continue
        if (settled.side or "").strip().upper() != live_side:
            continue
        if abs(settled.price - live.price) > _PRICE_EPS:
            continue
        if settled.executed_at.date() != live_day:
            continue
        return settled
    return None


def _is_bag_summary(live: LiveExecution) -> bool:
    """The live BAG summary fill of a combo order.

    Prefers ``exec_role`` (set at ingest since the combo-role work) and falls
    back to ``sec_type`` for rows written before it.
    """
    return live.exec_role == "combo_summary" or (live.sec_type or "").strip().upper() == "BAG"


def _bag_summary_clause():
    """SQL form of ``_is_bag_summary`` — keep the two in step when either changes."""
    return or_(
        LiveExecution.exec_role == "combo_summary",
        func.upper(func.trim(func.coalesce(LiveExecution.sec_type, ""))) == "BAG",
    )


def _order_group_key(live: LiveExecution) -> tuple[str, int] | None:
    """Key grouping a live BAG summary with its live legs.

    Mirrors ``intraday_sync_tws._order_group_key`` — prefers ``permId``, falls
    back to ``orderId`` — so the two stay in step. ``None`` when the row carries
    neither, in which case its legs cannot be identified and it is left alone.
    """
    if live.ib_perm_id:
        return ("perm", live.ib_perm_id)
    if live.ib_order_id:
        return ("order", live.ib_order_id)
    return None


def _has_live_siblings(session: Session, live: LiveExecution) -> bool:
    """True while any unsettled **leg** still shares this row's order key.

    A live leg only leaves ``live_executions`` by settling (the exact-id purge
    or the leg-strip matcher above), so "no legs left" is the proof that the
    combo's legs have settled. A summary whose legs are still live is deferred
    to a later run, after they reconcile.

    Peer BAG summaries are excluded from the count. When a combo order fills in
    several partial executions, TWS emits one BAG summary *per partial* — all
    sharing the order's ``permId``. Counting those as siblings deadlocked them
    against each other: each saw the other still present, so neither ever
    reached "no siblings" and both lingered as phantom ``unsettled`` rows even
    though every leg had settled. A peer summary is never evidence that a leg is
    outstanding, so only non-summary rows gate the purge.
    """
    key = _order_group_key(live)
    if key is None:
        return True
    kind, value = key
    column = LiveExecution.ib_perm_id if kind == "perm" else LiveExecution.ib_order_id
    remaining = session.execute(
        select(func.count()).select_from(LiveExecution).where(column == value, LiveExecution.id != live.id, ~_bag_summary_clause())
    ).scalar_one()
    return remaining > 0


def _settled_legs_at(session: Session, live: LiveExecution) -> list[TradeExecution]:
    """Settled combo legs booked at this summary's account and timestamp.

    The BAG summary and its legs share an ``exec_time`` on both feeds, so this
    corroborates that a combo really did settle here — guarding the case where a
    summary arrives with no legs in the live batch at all, which would otherwise
    satisfy the sibling check vacuously and purge before settlement.
    """
    return list(
        session.execute(
            select(TradeExecution).where(
                TradeExecution.account_id == live.account_id,
                TradeExecution.exec_role == "leg",
                TradeExecution.executed_at == live.exec_time,
            )
        )
        .scalars()
        .all()
    )


def _match_bag_summary(session: Session, live: LiveExecution) -> list[TradeExecution] | None:
    """Class C: a redundant live BAG summary whose combo has settled.

    Returns the settled legs to hand the group tag to, or ``None`` to leave the
    row in place. Unlike the other matchers this resolves no single settled twin
    — FlexQuery synthesizes its own combo summary, and there is no key to pair
    them on.
    """
    if not _is_bag_summary(live):
        return None
    if _order_group_key(live) is None:
        return None
    if _has_live_siblings(session, live):
        return None
    legs = _settled_legs_at(session, live)
    return legs or None


def reconcile_orphaned_live_executions(session: Session) -> dict[str, int]:
    """Purge live fills whose settled twin exists under a different ``ib_exec_id``.

    Runs after a FlexQuery sync (the authoritative source for every class here)
    and is safe to run repeatedly — it only ever acts on live rows not already
    present in ``trade_executions``. Returns counts
    ``{leg_strip, book_event, bag_summary, links_carried, unmatched}``.

    Order matters: BAG summaries are considered last, so a summary is only
    purged once this same pass has had the chance to reconcile its legs.
    """
    settled_subq = select(TradeExecution.ib_exec_id)
    orphans = session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.not_in(settled_subq))).scalars().all()
    counts = {"leg_strip": 0, "book_event": 0, "bag_summary": 0, "links_carried": 0, "unmatched": 0}
    if not orphans:
        return counts

    deferred: list[LiveExecution] = []
    for live in orphans:
        settled = _match_leg_strip(session, live)
        kind = "leg_strip"
        if settled is None:
            settled = _match_book_event(session, live)
            kind = "book_event"
        if settled is None:
            deferred.append(live)
            continue
        counts["links_carried"] += carry_over_link_to_execution(session, live.ib_exec_id, settled.id)
        session.delete(live)
        counts[kind] += 1

    # Legs purged above are still pending in the session; flush so the sibling
    # check below sees the post-reconcile state rather than the stale rows.
    if counts["leg_strip"] or counts["book_event"]:
        session.flush()

    for live in deferred:
        legs = _match_bag_summary(session, live)
        if legs is None:
            counts["unmatched"] += 1
            continue
        counts["links_carried"] += carry_over_link_to_executions(session, live.ib_exec_id, [leg.id for leg in legs])
        session.delete(live)
        counts["bag_summary"] += 1

    if counts["leg_strip"] or counts["book_event"] or counts["bag_summary"]:
        logger.info(
            "[live_reconcile] purged orphaned live fills: leg_strip=%d book_event=%d bag_summary=%d links_carried=%d unmatched=%d",
            counts["leg_strip"],
            counts["book_event"],
            counts["bag_summary"],
            counts["links_carried"],
            counts["unmatched"],
        )
    return counts
