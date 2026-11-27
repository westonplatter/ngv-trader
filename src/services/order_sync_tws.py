"""Broker order fetch/sync service.

Fetches open/recent broker orders and reconciles them into local `orders` and
`order_events` rows with idempotent matching by local orderRef and broker IDs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ib_async import IB, Trade
from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Account, Order
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_RECONCILE_REQUIRED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_SUBMITTED,
    ORDER_TERMINAL_STATUSES,
    append_order_event,
    can_transition_order_status,
    now_utc,
    transition_order_status,
)

DEFAULT_ORDER_SYNC_SOURCE = "broker_sync"
SWEEPABLE_STATUSES = (ORDER_STATUS_SUBMITTED, ORDER_STATUS_PARTIALLY_FILLED)


def parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_order_ref(order_ref: str | None) -> int | None:
    if order_ref is None:
        return None
    prefix = "ngtrader-order-"
    if not order_ref.startswith(prefix):
        return None
    raw = order_ref[len(prefix) :]
    try:
        return int(raw)
    except ValueError:
        return None


_IB_STATUS_TO_ORDER_STATUS = {
    "filled": ORDER_STATUS_FILLED,
    "rejected": ORDER_STATUS_REJECTED,
    "cancelled": ORDER_STATUS_CANCELLED,
    "apicancelled": ORDER_STATUS_CANCELLED,
    "inactive": ORDER_STATUS_CANCELLED,
}
_IB_WORKING_STATUSES = {"submitted", "presubmitted", "pendingsubmit"}


def normalize_ib_status(ib_status: str | None, filled_qty: float) -> str:
    value = (ib_status or "").strip().lower()
    mapped = _IB_STATUS_TO_ORDER_STATUS.get(value)
    if mapped is not None:
        return mapped
    if value in _IB_WORKING_STATUSES and filled_qty > 0:
        return ORDER_STATUS_PARTIALLY_FILLED
    if value:
        return ORDER_STATUS_SUBMITTED
    return ORDER_STATUS_QUEUED


def _trade_key(trade: Trade) -> tuple[int | None, int | None, str]:
    perm_id = parse_int(getattr(trade.order, "permId", None))
    order_id = parse_int(getattr(trade.order, "orderId", None))
    order_ref = str(getattr(trade.order, "orderRef", "") or "")
    return perm_id, order_id, order_ref


@dataclass(frozen=True)
class TradeFetch:
    trades: list[Trade]
    ok: bool


def _trades_from(fetch: Callable[[], Any]) -> tuple[list[Trade], bool]:
    """Run one broker fetch. The flag is False when it raised or returned something other than a list."""
    try:
        result = fetch()
    except Exception:
        return [], False
    if not isinstance(result, list):
        return [], False
    return [trade for trade in result if isinstance(trade, Trade)], True


def _fetch_open_trades(ib: IB) -> list[Trade]:
    ib.reqOpenOrders()
    ib.waitOnUpdate(timeout=1.0)
    return list(ib.openTrades())


def _collect_recent_trades(ib: IB) -> TradeFetch:
    # This client's open orders, every API client's open orders, then completed orders.
    open_trades, open_ok = _trades_from(lambda: _fetch_open_trades(ib))
    all_open_trades, all_open_ok = _trades_from(ib.reqAllOpenOrders)
    completed, completed_ok = _trades_from(lambda: ib.reqCompletedOrders(apiOnly=False))
    ok = open_ok and all_open_ok and completed_ok

    merged: list[Trade] = []
    seen: set[tuple[int | None, int | None, str]] = set()
    for trade in [*open_trades, *all_open_trades, *completed]:
        key = _trade_key(trade)
        if key in seen:
            continue
        seen.add(key)
        merged.append(trade)
    return TradeFetch(trades=merged, ok=ok)


def _ensure_account(session: Session, account_code: str) -> Account:
    stmt = select(Account).where(Account.account == account_code).limit(1)
    existing = session.execute(stmt).scalars().first()
    if existing is not None:
        return existing
    account = Account(account=account_code, alias=None)
    session.add(account)
    session.flush()
    return account


def _known_perm_id(trade: Trade) -> int | None:
    """The broker permId, or None while TWS has not assigned one (it reports 0)."""
    perm_id = parse_int(getattr(trade.order, "permId", None))
    return perm_id if perm_id else None


def _find_matching_order(session: Session, trade: Trade) -> Order | None:
    perm_id = _known_perm_id(trade)
    if perm_id is not None:
        stmt = select(Order).where(Order.ib_perm_id == perm_id).order_by(Order.updated_at.desc()).limit(1)
        matched = session.execute(stmt).scalars().first()
        if matched is not None:
            return matched

    local_order_id = parse_order_ref(getattr(trade.order, "orderRef", None))
    if local_order_id is not None:
        candidate = session.get(Order, local_order_id)
        if candidate is not None and candidate.source != DEFAULT_ORDER_SYNC_SOURCE and (candidate.ib_perm_id is None or candidate.ib_perm_id == perm_id):
            return candidate

    order_id = parse_int(getattr(trade.order, "orderId", None))
    client_id = parse_int(getattr(trade.order, "clientId", None))
    if order_id and client_id is not None:
        stmt = (
            select(Order)
            .where(Order.ib_order_id == order_id, Order.ib_client_id == client_id, Order.ib_perm_id.is_(None))
            .order_by(Order.updated_at.desc())
            .limit(1)
        )
        return session.execute(stmt).scalars().first()

    return None


def _safe_quantity(raw_quantity: Any) -> int:
    parsed = parse_float(raw_quantity)
    if parsed is None:
        return 1
    value = int(round(abs(parsed)))
    return value if value > 0 else 1


def _normalize_limit_price(order_type: str, raw_value: Any) -> float | None:
    value = parse_float(raw_value)
    if value is None:
        return None
    # For non-limit orders, IB often reports 0.0 placeholder prices.
    if order_type != "LMT" and value == 0.0:
        return None
    return value


def _normalize_side(raw_action: Any) -> str:
    action = str(raw_action or "BUY").strip().upper()
    if action in {"BUY", "SELL"}:
        return action
    return "BUY"


def _create_order_from_trade(session: Session, trade: Trade) -> Order:
    now = now_utc()
    account_code = str(getattr(trade.order, "account", "") or "").strip() or "UNKNOWN"
    account = _ensure_account(session, account_code)

    contract = trade.contract
    side = _normalize_side(getattr(trade.order, "action", None))
    filled_quantity = max(0.0, float(trade.filled() or 0.0))
    avg_fill_price = parse_float(getattr(trade.orderStatus, "avgFillPrice", None))
    normalized_status = normalize_ib_status(getattr(trade.orderStatus, "status", None), filled_quantity)
    submitted_at = now if normalized_status != ORDER_STATUS_QUEUED else None
    completed_at = now if normalized_status in ORDER_TERMINAL_STATUSES else None

    order_type = str(getattr(trade.order, "orderType", "") or "MKT").upper()
    order = Order(
        account_id=account.id,
        symbol=str(getattr(contract, "symbol", "") or "UNKNOWN").upper(),
        sec_type=str(getattr(contract, "secType", "") or "FUT").upper(),
        exchange=str(getattr(contract, "exchange", "") or "SMART").upper(),
        currency=str(getattr(contract, "currency", "") or "USD").upper(),
        side=side,
        quantity=_safe_quantity(getattr(trade.order, "totalQuantity", None)),
        order_type=order_type,
        limit_price=_normalize_limit_price(order_type, getattr(trade.order, "lmtPrice", None)),
        tif=str(getattr(trade.order, "tif", "") or "DAY").upper(),
        status=normalized_status,
        source=DEFAULT_ORDER_SYNC_SOURCE,
        con_id=parse_int(getattr(contract, "conId", None)),
        local_symbol=str(getattr(contract, "localSymbol", "") or "") or None,
        trading_class=str(getattr(contract, "tradingClass", "") or "") or None,
        contract_expiry=str(getattr(contract, "lastTradeDateOrContractMonth", "") or "") or None,
        ib_order_id=parse_int(getattr(trade.order, "orderId", None)),
        ib_client_id=parse_int(getattr(trade.order, "clientId", None)),
        ib_perm_id=_known_perm_id(trade),
        filled_quantity=filled_quantity,
        avg_fill_price=avg_fill_price,
        request_text=f"Imported from broker sync (orderRef={getattr(trade.order, 'orderRef', None)}).",
        submitted_at=submitted_at,
        completed_at=completed_at,
        created_at=now,
        updated_at=now,
    )
    session.add(order)
    session.flush()
    append_order_event(
        session=session,
        order_id=order.id,
        event_type="broker_order_synced_create",
        message=(
            f"Created from broker order sync: ib_status={getattr(trade.orderStatus, 'status', None)}, "
            f"ib_order_id={order.ib_order_id}, ib_perm_id={order.ib_perm_id}"
        ),
        status=order.status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
    return order


def _order_snapshot(order: Order) -> tuple:
    """The broker-synced fields of an order, compared before and after a sync to detect a change."""
    return (
        order.symbol,
        order.sec_type,
        order.exchange,
        order.currency,
        order.side,
        order.quantity,
        order.order_type,
        order.limit_price,
        order.tif,
        order.status,
        order.filled_quantity,
        order.avg_fill_price,
        order.ib_order_id,
        order.ib_perm_id,
        order.ib_client_id,
        order.con_id,
        order.local_symbol,
        order.trading_class,
        order.contract_expiry,
    )


def _apply_trade_fields(order: Order, trade: Trade, filled_quantity: float, avg_fill_price: float | None, now: datetime) -> None:
    contract = trade.contract

    # Broker state is source-of-truth for identity and execution attributes.
    order.symbol = str(getattr(contract, "symbol", "") or order.symbol).upper()
    order.sec_type = str(getattr(contract, "secType", "") or order.sec_type).upper()
    order.exchange = str(getattr(contract, "exchange", "") or order.exchange).upper()
    order.currency = str(getattr(contract, "currency", "") or order.currency).upper()
    order.side = _normalize_side(getattr(trade.order, "action", None))
    order.quantity = _safe_quantity(getattr(trade.order, "totalQuantity", None))
    order.order_type = str(getattr(trade.order, "orderType", "") or order.order_type).upper()
    order.limit_price = _normalize_limit_price(order.order_type, getattr(trade.order, "lmtPrice", None))
    order.tif = str(getattr(trade.order, "tif", "") or order.tif).upper()
    order.con_id = parse_int(getattr(contract, "conId", None)) or order.con_id
    local_symbol = str(getattr(contract, "localSymbol", "") or "") or None
    order.local_symbol = local_symbol if local_symbol is not None else order.local_symbol
    trading_class = str(getattr(contract, "tradingClass", "") or "") or None
    order.trading_class = trading_class if trading_class is not None else order.trading_class
    contract_expiry = str(getattr(contract, "lastTradeDateOrContractMonth", "") or "") or None
    order.contract_expiry = contract_expiry if contract_expiry is not None else order.contract_expiry
    order.ib_order_id = parse_int(getattr(trade.order, "orderId", None)) or order.ib_order_id
    order.ib_perm_id = _known_perm_id(trade) or order.ib_perm_id
    client_id = parse_int(getattr(trade.order, "clientId", None))
    if client_id is not None:
        order.ib_client_id = client_id
    order.filled_quantity = filled_quantity
    order.avg_fill_price = avg_fill_price
    order.updated_at = now


def _reconcile_order_status(session: Session, order: Order, trade: Trade, normalized_status: str, now: datetime) -> bool:
    """Move the order to the broker's status. Returns True when a status event was appended."""
    if order.status == normalized_status:
        session.flush()
        return False

    if can_transition_order_status(order.status, normalized_status):
        transition_order_status(
            session=session,
            order=order,
            next_status=normalized_status,
            event_type="broker_order_synced_status",
            message=(
                f"Broker order sync status update: ib_status={getattr(trade.orderStatus, 'status', None)}, "
                f"filled={order.filled_quantity}, avg_fill={order.avg_fill_price}"
            ),
        )
        return True

    order.status = normalized_status
    if normalized_status in ORDER_TERMINAL_STATUSES and order.completed_at is None:
        order.completed_at = now
    session.flush()
    append_order_event(
        session=session,
        order_id=order.id,
        event_type="broker_order_synced_status",
        message=f"Forced status update to {normalized_status} from broker sync.",
        status=order.status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
    return True


def _sync_trade_onto_order(session: Session, order: Order, trade: Trade) -> bool:
    prev = _order_snapshot(order)
    now = now_utc()
    filled_quantity = max(0.0, float(trade.filled() or 0.0))
    normalized_status = normalize_ib_status(getattr(trade.orderStatus, "status", None), filled_quantity)
    avg_fill_price = parse_float(getattr(trade.orderStatus, "avgFillPrice", None))

    _apply_trade_fields(order, trade, filled_quantity, avg_fill_price, now)
    if order.submitted_at is None and normalized_status != ORDER_STATUS_QUEUED:
        order.submitted_at = now

    emitted_status_event = _reconcile_order_status(session, order, trade, normalized_status, now)

    if _order_snapshot(order) == prev:
        return False

    if normalized_status in ORDER_TERMINAL_STATUSES and order.completed_at is None:
        order.completed_at = now
        session.flush()

    if not emitted_status_event:
        append_order_event(
            session=session,
            order_id=order.id,
            event_type="broker_order_synced_update",
            message=(
                f"Broker order sync refreshed order fields: ib_status={getattr(trade.orderStatus, 'status', None)}, "
                f"ib_order_id={order.ib_order_id}, ib_perm_id={order.ib_perm_id}"
            ),
            status=order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            ib_order_id=order.ib_order_id,
        )
    return True


@dataclass(frozen=True)
class OrderApplyResult:
    order: Order
    created: bool
    changed: bool


def apply_trade_to_order(session: Session, trade: Trade) -> OrderApplyResult:
    """Match a broker trade to a local order, then create or update it. Does not commit."""
    order = _find_matching_order(session, trade)
    if order is None:
        order = _create_order_from_trade(session, trade)
        order.last_seen_at = now_utc()
        return OrderApplyResult(order=order, created=True, changed=True)
    changed = _sync_trade_onto_order(session, order, trade)
    order.last_seen_at = now_utc()
    return OrderApplyResult(order=order, created=False, changed=changed)


def sweep_unseen_working_orders(session: Session, fetch_started_at: datetime) -> list[int]:
    """Move working orders the broker no longer reports to reconcile_required. Does not commit."""
    stale = (
        session.execute(
            select(Order).where(
                Order.status.in_(SWEEPABLE_STATUSES),
                or_(Order.last_seen_at.is_(None), Order.last_seen_at < fetch_started_at),
                Order.updated_at < fetch_started_at,
            )
        )
        .scalars()
        .all()
    )
    for order in stale:
        transition_order_status(
            session=session,
            order=order,
            next_status=ORDER_STATUS_RECONCILE_REQUIRED,
            event_type="broker_order_missing",
            message="Order missing from a successful broker fetch; needs reconcile.",
        )
    return [order.id for order in stale]


def sync_orders_once(
    engine: Engine,
    *,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out connecting to TWS/Gateway while fetching orders "
                f"(host={host}, port={port}, client_id={client_id}, timeout={connect_timeout_seconds}s)."
            ) from exc
        return sync_orders_with_ib(engine=engine, ib=ib)
    finally:
        if ib.isConnected():
            ib.disconnect()


def sync_orders_with_ib(
    engine: Engine,
    *,
    ib: IB,
) -> dict[str, Any]:
    fetch_started_at = now_utc()
    fetch = _collect_recent_trades(ib)
    trades = fetch.trades
    created_ids: list[int] = []
    updated_ids: list[int] = []
    with Session(engine) as session:
        for trade in trades:
            result = apply_trade_to_order(session, trade)
            if result.created:
                created_ids.append(result.order.id)
            elif result.changed:
                updated_ids.append(result.order.id)
        if fetch.ok:
            swept_ids = sweep_unseen_working_orders(session, fetch_started_at)
            updated_ids.extend(order_id for order_id in swept_ids if order_id not in updated_ids)
        session.commit()

    return {
        "fetched_trades_count": len(trades),
        "created_orders_count": len(created_ids),
        "updated_orders_count": len(updated_ids),
        "created_order_ids": created_ids,
        "updated_order_ids": updated_ids,
    }
