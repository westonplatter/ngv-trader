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

Not handled (left in place, all carry zero realized P&L): live BAG combo-summary
rows on a placeholder ``con_id`` have no settled counterpart keyed by
``con_id`` and need an order/perm-id key ``live_executions`` does not yet
capture (see docs/plans/2026-07-08-001-feat-unsettled-tws-contract-parity-plan.md,
Fix C). Reconciling those is a follow-up gated on that migration.

When a match is found, any preemptive trade-group tag on the live fill is
carried onto the settled execution before the live row is deleted, so grouping
survives the handoff with no gap and no double-count.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import LiveExecution, TradeExecution
from src.services.group_link_carryover import carry_over_link_to_execution

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


def reconcile_orphaned_live_executions(session: Session) -> dict[str, int]:
    """Purge live fills whose settled twin exists under a different ``ib_exec_id``.

    Runs after a FlexQuery sync (the authoritative source for both id-divergence
    classes) and is safe to run repeatedly — it only ever acts on live rows not
    already present in ``trade_executions``. Returns counts
    ``{leg_strip, book_event, links_carried, unmatched}``.
    """
    settled_subq = select(TradeExecution.ib_exec_id)
    orphans = session.execute(select(LiveExecution).where(LiveExecution.ib_exec_id.not_in(settled_subq))).scalars().all()
    if not orphans:
        return {"leg_strip": 0, "book_event": 0, "links_carried": 0, "unmatched": 0}

    counts = {"leg_strip": 0, "book_event": 0, "links_carried": 0, "unmatched": 0}
    for live in orphans:
        settled = _match_leg_strip(session, live)
        kind = "leg_strip"
        if settled is None:
            settled = _match_book_event(session, live)
            kind = "book_event"
        if settled is None:
            counts["unmatched"] += 1
            continue
        counts["links_carried"] += carry_over_link_to_execution(session, live.ib_exec_id, settled.id)
        session.delete(live)
        counts[kind] += 1

    if counts["leg_strip"] or counts["book_event"]:
        logger.info(
            "[live_reconcile] purged orphaned live fills: leg_strip=%d book_event=%d " "links_carried=%d unmatched=%d",
            counts["leg_strip"],
            counts["book_event"],
            counts["links_carried"],
            counts["unmatched"],
        )
    return counts
