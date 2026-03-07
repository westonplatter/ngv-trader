"""Broker order fetch/sync service.

Fetches open/recent broker orders and reconciles them into local `orders` and
`order_events` rows with idempotent matching by local orderRef and broker IDs.
"""

from __future__ import annotations

from typing import Any

from ib_async import IB, Trade
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Account, Order
from src.services.order_queue import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_REJECTED,
    ORDER_STATUS_SUBMITTED,
    ORDER_TERMINAL_STATUSES,
    append_order_event,
    can_transition_order_status,
    now_utc,
    transition_order_status,
)

DEFAULT_ORDER_SYNC_SOURCE = "broker_sync"


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


def normalize_ib_status(ib_status: str | None, filled_qty: float) -> str:
    value = (ib_status or "").strip().lower()
    if value == "filled":
        return ORDER_STATUS_FILLED
    if value == "rejected":
        return ORDER_STATUS_REJECTED
    if value in {"cancelled", "apicancelled", "inactive"}:
        return ORDER_STATUS_CANCELLED
    if value in {"submitted", "presubmitted", "pendingsubmit"}:
        if filled_qty > 0:
            return ORDER_STATUS_PARTIALLY_FILLED
        return ORDER_STATUS_SUBMITTED
    if value:
        return ORDER_STATUS_SUBMITTED
    return ORDER_STATUS_QUEUED


def _trade_key(trade: Trade) -> tuple[int | None, int | None, str]:
    perm_id = parse_int(getattr(trade.order, "permId", None))
    order_id = parse_int(getattr(trade.order, "orderId", None))
    order_ref = str(getattr(trade.order, "orderRef", "") or "")
    return perm_id, order_id, order_ref


def _collect_recent_trades(ib: IB, *, client_id: int) -> list[Trade]:
    # Best-effort bind for manually-entered TWS orders when permissions/client-id allow.
    if client_id == 0:
        try:
            ib.reqAutoOpenOrders(True)
        except Exception:  # nosec B110 - best-effort; TWS may reject depending on client permissions
            pass

    # Pull open orders from this client scope.
    ib.reqOpenOrders()
    ib.waitOnUpdate(timeout=1.0)
    open_trades = list(ib.openTrades())

    # Pull open orders across all API clients.
    all_open_trades: list[Trade] = []
    try:
        maybe_all_open = ib.reqAllOpenOrders()
        if isinstance(maybe_all_open, list):
            all_open_trades = [trade for trade in maybe_all_open if isinstance(trade, Trade)]
    except Exception:
        all_open_trades = []

    completed: list[Trade] = []
    try:
        maybe_completed = ib.reqCompletedOrders(apiOnly=False)
        if isinstance(maybe_completed, list):
            completed = [trade for trade in maybe_completed if isinstance(trade, Trade)]
    except Exception:
        completed = []

    merged: list[Trade] = []
    seen: set[tuple[int | None, int | None, str]] = set()
    for trade in [*open_trades, *all_open_trades, *completed]:
        key = _trade_key(trade)
        if key in seen:
            continue
        seen.add(key)
        merged.append(trade)
    return merged


def _ensure_account(session: Session, account_code: str) -> Account:
    stmt = select(Account).where(Account.account == account_code).limit(1)
    existing = session.execute(stmt).scalars().first()
    if existing is not None:
        return existing
    account = Account(account=account_code, alias=None)
    session.add(account)
    session.flush()
    return account


def _find_matching_order(session: Session, trade: Trade) -> Order | None:
    local_order_id = parse_order_ref(getattr(trade.order, "orderRef", None))
    if local_order_id is not None:
        matched = session.get(Order, local_order_id)
        if matched is not None:
            return matched

    perm_id = parse_int(getattr(trade.order, "permId", None))
    if perm_id is not None:
        stmt = select(Order).where(Order.ib_perm_id == perm_id).order_by(Order.updated_at.desc()).limit(1)
        matched = session.execute(stmt).scalars().first()
        if matched is not None:
            return matched

    order_id = parse_int(getattr(trade.order, "orderId", None))
    if order_id is not None:
        stmt = select(Order).where(Order.ib_order_id == order_id).order_by(Order.updated_at.desc()).limit(1)
        matched = session.execute(stmt).scalars().first()
        if matched is not None:
            return matched

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
        ib_perm_id=parse_int(getattr(trade.order, "permId", None)),
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


def _sync_trade_onto_order(session: Session, order: Order, trade: Trade) -> bool:
    prev = (
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
        order.con_id,
        order.local_symbol,
        order.trading_class,
        order.contract_expiry,
    )
    now = now_utc()
    filled_quantity = max(0.0, float(trade.filled() or 0.0))
    normalized_status = normalize_ib_status(getattr(trade.orderStatus, "status", None), filled_quantity)
    avg_fill_price = parse_float(getattr(trade.orderStatus, "avgFillPrice", None))
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
    order.ib_perm_id = parse_int(getattr(trade.order, "permId", None)) or order.ib_perm_id
    order.filled_quantity = filled_quantity
    order.avg_fill_price = avg_fill_price
    order.updated_at = now
    if order.submitted_at is None and normalized_status != ORDER_STATUS_QUEUED:
        order.submitted_at = now

    status_changed = order.status != normalized_status
    emitted_status_event = False
    if status_changed:
        if can_transition_order_status(order.status, normalized_status):
            transition_order_status(
                session=session,
                order=order,
                next_status=normalized_status,
                event_type="broker_order_synced_status",
                message=(
                    f"Broker order sync status update: ib_status={getattr(trade.orderStatus, 'status', None)}, "
                    f"filled={filled_quantity}, avg_fill={avg_fill_price}"
                ),
            )
            emitted_status_event = True
        else:
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
            emitted_status_event = True
    else:
        session.flush()

    current = (
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
        order.con_id,
        order.local_symbol,
        order.trading_class,
        order.contract_expiry,
    )
    if current == prev:
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


def sync_orders_once(
    engine: Engine,
    *,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 20.0,
) -> dict[str, int]:
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out connecting to TWS/Gateway while fetching orders "
                f"(host={host}, port={port}, client_id={client_id}, timeout={connect_timeout_seconds}s)."
            ) from exc
        return sync_orders_with_ib(
            engine=engine,
            ib=ib,
            client_id=client_id,
        )
    finally:
        if ib.isConnected():
            ib.disconnect()


def sync_orders_with_ib(
    engine: Engine,
    *,
    ib: IB,
    client_id: int,
) -> dict[str, int]:
    trades = _collect_recent_trades(ib, client_id=client_id)
    created_count = 0
    updated_count = 0
    with Session(engine) as session:
        for trade in trades:
            order = _find_matching_order(session, trade)
            if order is None:
                _create_order_from_trade(session, trade)
                created_count += 1
                continue
            if _sync_trade_onto_order(session, order, trade):
                updated_count += 1
        session.commit()

    return {
        "fetched_trades_count": len(trades),
        "created_orders_count": created_count,
        "updated_orders_count": updated_count,
    }
