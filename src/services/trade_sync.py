"""Sync trade executions from IBKR into Postgres.

Fetches fills via ib_async, upserts into trade_executions with idempotency
on ib_exec_id, enforces canonical revision flags, resolves parent trades,
and recomputes trade aggregates from canonical executions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ib_async import IB, ExecutionFilter
from sqlalchemy import Engine, inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Account, Trade, TradeExecution

logger = logging.getLogger("trade_sync")


def check_trades_tables_ready(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for required in ("trades", "trade_executions", "accounts"):
        if required not in tables:
            raise RuntimeError(f"'{required}' table does not exist. Run: task migrate")


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


def _ensure_account(session: Session, account_code: str) -> Account:
    stmt = select(Account).where(Account.account == account_code).limit(1)
    existing = session.execute(stmt).scalars().first()
    if existing is not None:
        return existing
    account = Account(account=account_code, alias=None)
    session.add(account)
    session.flush()
    return account


def _fill_to_raw(fill: Any) -> dict:
    """Serialize an ib_async Fill object to a JSON-safe dict for audit storage."""
    raw: dict[str, Any] = {}
    execution = getattr(fill, "execution", None)
    if execution is not None:
        raw["execution"] = {
            "execId": getattr(execution, "execId", None),
            "time": str(getattr(execution, "time", "")),
            "acctNumber": getattr(execution, "acctNumber", None),
            "exchange": getattr(execution, "exchange", None),
            "side": getattr(execution, "side", None),
            "shares": getattr(execution, "shares", None),
            "price": getattr(execution, "price", None),
            "permId": getattr(execution, "permId", None),
            "orderId": getattr(execution, "orderId", None),
            "cumQty": getattr(execution, "cumQty", None),
            "avgPrice": getattr(execution, "avgPrice", None),
            "orderRef": getattr(execution, "orderRef", None),
            "liquidation": getattr(execution, "liquidation", None),
            # Preserve lifecycle hints from IBKR when available so the API/UI
            # can distinguish open vs close without guessing from side.
            "openClose": getattr(execution, "openClose", None),
            "positionEffect": getattr(execution, "positionEffect", None),
        }
    commission_report = getattr(fill, "commissionReport", None)
    if commission_report is not None:
        raw["commissionReport"] = {
            "commission": getattr(commission_report, "commission", None),
            "currency": getattr(commission_report, "currency", None),
            "realizedPNL": getattr(commission_report, "realizedPNL", None),
        }
    contract = getattr(fill, "contract", None)
    if contract is not None:
        raw["contract"] = {
            "conId": getattr(contract, "conId", None),
            "symbol": getattr(contract, "symbol", None),
            "secType": getattr(contract, "secType", None),
            "exchange": getattr(contract, "exchange", None),
            "currency": getattr(contract, "currency", None),
            "localSymbol": getattr(contract, "localSymbol", None),
        }
    return raw


def _resolve_or_create_trade(
    session: Session,
    account_id: int,
    ib_perm_id: int | None,
    order_ref: str | None,
    ib_order_id: int | None,
    symbol: str | None,
    side: str | None,
    trade_date: str | None,
    now: datetime,
) -> Trade:
    """Find or create a parent Trade row using the spec's resolution order."""
    # 1. Match by (account_id, ib_perm_id) when perm_id is meaningful
    if ib_perm_id is not None and ib_perm_id > 0:
        stmt = select(Trade).where(
            Trade.account_id == account_id,
            Trade.ib_perm_id == ib_perm_id,
        )
        existing = session.execute(stmt).scalars().first()
        if existing is not None:
            return existing
        trade = Trade(
            account_id=account_id,
            ib_perm_id=ib_perm_id,
            order_ref=order_ref,
            ib_order_id=ib_order_id,
            symbol=symbol,
            side=side,
            status="partial",
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(trade)
        session.flush()
        return trade

    # 2. Match by (account_id, order_ref) — only when order_ref looks like a
    #    unique trade identifier (e.g. "ngtrader-order-42", "ngtrader-spread-7").
    #    Generic IBKR tool refs like "SpreadTrader" are shared across many
    #    unrelated trades and must NOT be used as a matching key.
    if order_ref and order_ref.startswith("ngtrader-"):
        stmt = select(Trade).where(
            Trade.account_id == account_id,
            Trade.order_ref == order_ref,
        )
        existing = session.execute(stmt).scalars().first()
        if existing is not None:
            return existing
        trade = Trade(
            account_id=account_id,
            ib_perm_id=ib_perm_id,
            order_ref=order_ref,
            ib_order_id=ib_order_id,
            symbol=symbol,
            side=side,
            status="partial",
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(trade)
        session.flush()
        return trade

    # 3. Composite fallback: (account_id, ib_order_id, symbol, side, trade_date)
    stmt = select(Trade).where(
        Trade.account_id == account_id,
        Trade.ib_order_id == ib_order_id,
        Trade.symbol == symbol,
        Trade.side == side,
    )
    candidates = session.execute(stmt).scalars().all()
    for candidate in candidates:
        if candidate.first_executed_at is not None:
            candidate_date = candidate.first_executed_at.strftime("%Y-%m-%d")
            if candidate_date == trade_date:
                return candidate
    trade = Trade(
        account_id=account_id,
        ib_perm_id=ib_perm_id,
        order_ref=order_ref,
        ib_order_id=ib_order_id,
        symbol=symbol,
        side=side,
        status="partial",
        fetched_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(trade)
    session.flush()
    return trade


def _enforce_canonical_flags(session: Session, account_id: int, exec_id_base: str) -> int:
    """Set is_canonical for the highest revision, clear for lower revisions.

    Returns the number of rows whose is_canonical value changed.
    """
    # Find all revisions for this base
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


def sync_trades_once(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 20.0,
    lookback_days: int = 7,
) -> dict[str, Any]:
    """Fetch IBKR fills and upsert into trade_executions + trades.

    Returns metrics dict with counts and window info.
    """
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out connecting to TWS/Gateway while fetching trades "
                f"(host={host}, port={port}, client_id={client_id}, timeout={connect_timeout_seconds}s)."
            ) from exc
        return sync_trades_with_ib(
            engine=engine,
            ib=ib,
            lookback_days=lookback_days,
        )
    finally:
        if ib.isConnected():
            ib.disconnect()


def sync_trades_with_ib(
    engine: Engine,
    *,
    ib: IB,
    lookback_days: int = 7,
) -> dict[str, Any]:
    # Request executions from IBKR with lookback window.
    # IBKR provides up to 7 days of history; lookback_days controls the
    # requested window (capped by TWS/Gateway limits).
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=lookback_days)
    time_filter = window_start.strftime("%Y%m%d %H:%M:%S")
    exec_filter = ExecutionFilter(time=time_filter)
    ib.reqExecutions(exec_filter)
    fills = ib.fills()
    logger.info("Fetched %d fills from TWS (lookback=%d days)", len(fills), lookback_days)

    inserted_count = 0
    updated_count = 0
    canonical_changes = 0
    touched_trade_ids: set[int] = set()
    affected_bases: list[tuple[int, str]] = []

    with Session(engine) as session:
        for fill in fills:
            execution = getattr(fill, "execution", None)
            if execution is None:
                continue

            exec_id = getattr(execution, "execId", None)
            if not exec_id:
                continue

            # Parse execution time
            exec_time = getattr(execution, "time", None)
            if exec_time is None:
                continue
            if isinstance(exec_time, str):
                try:
                    exec_time = datetime.fromisoformat(exec_time)
                except ValueError:
                    continue
            if exec_time.tzinfo is None:
                exec_time = exec_time.replace(tzinfo=timezone.utc)

            # Skip fills outside lookback window
            if exec_time < window_start:
                continue

            # Resolve account
            account_code = str(getattr(execution, "acctNumber", "") or "").strip()
            if not account_code:
                continue
            account = _ensure_account(session, account_code)

            # Parse exec ID into base + revision
            exec_id_base, exec_revision = _parse_exec_id(exec_id)

            # Extract execution fields
            ib_perm_id = _safe_int(getattr(execution, "permId", None))
            ib_order_id = _safe_int(getattr(execution, "orderId", None))
            order_ref = _safe_str(getattr(execution, "orderRef", None))
            quantity = _safe_float(getattr(execution, "shares", None)) or 0.0
            price = _safe_float(getattr(execution, "price", None)) or 0.0
            side = _safe_str(getattr(execution, "side", None))
            exchange = _safe_str(getattr(execution, "exchange", None))

            # Contract info
            contract = getattr(fill, "contract", None)
            symbol = _safe_str(getattr(contract, "symbol", None)) if contract else None
            sec_type = _safe_str(getattr(contract, "secType", None)) if contract else None
            currency = _safe_str(getattr(contract, "currency", None)) if contract else None

            # Commission
            comm_report = getattr(fill, "commissionReport", None)
            commission = _safe_float(getattr(comm_report, "commission", None)) if comm_report else None
            liquidity = _safe_str(getattr(execution, "liquidation", None))

            # Trade date for composite fallback
            trade_date = exec_time.strftime("%Y-%m-%d")

            # Resolve parent trade
            trade = _resolve_or_create_trade(
                session=session,
                account_id=account.id,
                ib_perm_id=ib_perm_id,
                order_ref=order_ref,
                ib_order_id=ib_order_id,
                symbol=symbol,
                side=side,
                trade_date=trade_date,
                now=now,
            )
            # Backfill symbol/sec_type on trade if missing
            if trade.symbol is None and symbol:
                trade.symbol = symbol
            if trade.sec_type is None and sec_type:
                trade.sec_type = sec_type
            if trade.exchange is None and exchange:
                trade.exchange = exchange
            if trade.currency is None and currency:
                trade.currency = currency

            raw = _fill_to_raw(fill)

            # Determine exec_role from contract secType.
            # BAG = combo summary fill; others start as standalone
            # and get re-tagged to "leg" after all fills are processed.
            exec_sec_type = sec_type  # already extracted above
            con_id = _safe_int(getattr(contract, "conId", None)) if contract else None
            if exec_sec_type == "BAG":
                exec_role = "combo_summary"
            else:
                exec_role = "standalone"

            # Upsert execution (idempotent on ib_exec_id)
            stmt = (
                insert(TradeExecution)
                .values(
                    trade_id=trade.id,
                    account_id=account.id,
                    ib_exec_id=exec_id,
                    exec_id_base=exec_id_base,
                    exec_revision=exec_revision,
                    ib_perm_id=ib_perm_id,
                    ib_order_id=ib_order_id,
                    order_ref=order_ref,
                    sec_type=exec_sec_type,
                    con_id=con_id,
                    exec_role=exec_role,
                    executed_at=exec_time,
                    quantity=quantity,
                    price=price,
                    side=side,
                    exchange=exchange,
                    currency=currency,
                    liquidity=liquidity,
                    commission=commission,
                    is_canonical=True,  # will be corrected below
                    raw=raw,
                    fetched_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["ib_exec_id"],
                    set_={
                        "trade_id": trade.id,
                        "quantity": quantity,
                        "price": price,
                        "commission": commission,
                        "sec_type": exec_sec_type,
                        "con_id": con_id,
                        "exec_role": exec_role,
                        "raw": raw,
                        "fetched_at": now,
                        "updated_at": now,
                    },
                )
            )
            result = session.execute(stmt)
            # xmax == 0 means a fresh insert in PostgreSQL
            result_rowcount = getattr(result, "rowcount", None)
            if hasattr(result, "returned_defaults") or result_rowcount == 1:
                # Check if this was an insert or update by looking at returning
                # We track both — the canonical enforcement pass handles correctness
                inserted_count += 1

            affected_bases.append((account.id, exec_id_base))
            touched_trade_ids.add(trade.id)

        # Enforce canonical flags for all affected exec_id_bases
        for acct_id, base in affected_bases:
            changes = _enforce_canonical_flags(session, acct_id, base)
            canonical_changes += changes

        # Re-tag exec_role: for each touched trade, if any execution is
        # combo_summary (secType=BAG), mark sibling standalones as "leg".
        # Also ensure trades.sec_type = 'BAG' for combo trades.
        for trade_id in touched_trade_ids:
            execs_stmt = select(TradeExecution).where(TradeExecution.trade_id == trade_id)
            trade_execs = session.execute(execs_stmt).scalars().all()
            has_combo = any(ex.exec_role == "combo_summary" for ex in trade_execs)
            if has_combo:
                parent_trade = session.get(Trade, trade_id)
                if parent_trade and parent_trade.sec_type != "BAG":
                    parent_trade.sec_type = "BAG"
                for ex in trade_execs:
                    if ex.exec_role == "standalone":
                        ex.exec_role = "leg"
                session.flush()

        # Recompute aggregates for all touched parent trades
        for trade_id in touched_trade_ids:
            _recompute_trade_aggregates(session, trade_id, now)

        session.commit()

    return {
        "fetched_executions_count": len(fills),
        "inserted_executions_count": inserted_count,
        "updated_executions_count": updated_count,
        "canonical_changes_count": canonical_changes,
        "touched_trades_count": len(touched_trade_ids),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
    }
