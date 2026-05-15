"""Shared helpers used by both TWS-backed and Flex Query-backed sync paths.

This module is the neutral home for row-coercion helpers, account upserts, and
trade-execution machinery that historically lived in trade_sync.py /
position_sync.py and was cross-imported by the Flex Query sync modules. Keep
this module free of TWS- or Flex-specific dependencies so neither side has to
cross-import the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Account, Trade, TradeExecution


def _safe_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _safe_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _parse_exec_id(ib_exec_id: str) -> tuple[str, int]:
    """Parse ib_exec_id into (exec_id_base, exec_revision).

    IBKR exec IDs use the digits after the final '.' as the revision.
    e.g. '0001f4e8.67890abc.01' -> base='0001f4e8.67890abc.', revision=1
    """
    dot_pos = ib_exec_id.rfind(".")
    if dot_pos < 0:
        return ib_exec_id + ".", 1
    base = ib_exec_id[: dot_pos + 1]  # includes trailing dot
    suffix = ib_exec_id[dot_pos + 1 :]
    try:
        revision = int(suffix)
    except (ValueError, TypeError):
        revision = 1
    return base, revision


def _ensure_account(session: Session, account_code: str) -> Account:
    stmt = select(Account).where(Account.account == account_code).limit(1)
    existing = session.execute(stmt).scalars().first()
    if existing is not None:
        return existing
    account = Account(account=account_code, alias=None)
    session.add(account)
    session.flush()
    return account


def get_or_create_accounts(session: Session, account_strings: set[str]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for account_string in account_strings:
        row = session.execute(select(Account).where(Account.account == account_string)).scalar_one_or_none()
        if row is None:
            row = Account(account=account_string)
            session.add(row)
            session.flush()
        lookup[account_string] = row.id
    return lookup


def _enforce_canonical_flags(session: Session, account_id: int, exec_id_base: str) -> int:
    """Set is_canonical for the highest revision, clear for lower revisions.

    Returns the number of rows whose is_canonical value changed.
    """
    stmt = (
        select(TradeExecution)
        .where(
            TradeExecution.account_id == account_id,
            TradeExecution.exec_id_base == exec_id_base,
        )
        .order_by(TradeExecution.exec_revision.desc())
    )
    rows = session.execute(stmt).scalars().all()
    if not rows:
        return 0

    changes = 0
    for i, row in enumerate(rows):
        should_be_canonical = i == 0  # highest revision first
        if row.is_canonical != should_be_canonical:
            row.is_canonical = should_be_canonical
            changes += 1
    if changes:
        session.flush()
    return changes


def _recompute_trade_aggregates(session: Session, trade_id: int, now: datetime) -> None:
    """Recompute parent trade aggregates from canonical executions only."""
    stmt = select(TradeExecution).where(
        TradeExecution.trade_id == trade_id,
        TradeExecution.is_canonical.is_(True),
    )
    canonical = session.execute(stmt).scalars().all()

    trade = session.get(Trade, trade_id)
    if trade is None:
        return

    if not canonical:
        trade.total_quantity = 0.0
        trade.avg_price = None
        trade.first_executed_at = None
        trade.last_executed_at = None
        trade.status = "unknown"
        trade.updated_at = now
        session.flush()
        return

    # Deterministic combo/spread detection using exec_role.
    # combo_summary fills have the spread's net price and quantity.
    # Leg fills are audit detail, not used for parent trade aggregates.
    combo_fills = [ex for ex in canonical if ex.exec_role == "combo_summary"]

    if combo_fills:
        # Spread trade — aggregate from combo-level fills only.
        total_qty = sum(abs(cf.quantity) for cf in combo_fills)
        weighted = sum(abs(cf.quantity) * cf.price for cf in combo_fills)
        avg_price = weighted / total_qty if total_qty > 0 else None
    else:
        # Regular (non-spread) trade — sum all fills directly.
        total_qty = sum(abs(ex.quantity) for ex in canonical)
        weighted = sum(abs(ex.quantity) * ex.price for ex in canonical)
        avg_price = weighted / total_qty if total_qty > 0 else None
    first_at = min(ex.executed_at for ex in canonical)
    last_at = max(ex.executed_at for ex in canonical)

    trade.total_quantity = total_qty
    trade.avg_price = avg_price
    trade.first_executed_at = first_at
    trade.last_executed_at = last_at
    trade.status = "filled"
    trade.fetched_at = now
    trade.updated_at = now
    session.flush()
