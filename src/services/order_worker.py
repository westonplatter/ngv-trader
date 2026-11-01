"""Order worker policy: status normalization, contract qualification, and reconciliation.

This module owns the order-lifecycle functions the order worker applies to a
single order: mapping IB statuses onto ours, qualifying contracts, applying
`Trade` progress to an `Order`, processing a claimed order, and reconciling
open orders against TWS at startup. The CLI entrypoint in
`scripts/work_order_queue.py` imports these and drives the claim/poll loop.
"""

from __future__ import annotations

import time
from typing import Any

from ib_async import IB, Contract, LimitOrder, MarketOrder, Trade
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Account, Order
from src.services.cl_contracts import (
    DEFAULT_CL_MIN_DAYS_TO_EXPIRY,
    contract_days_to_expiry,
    select_front_month_contract,
    select_front_month_future_contract,
)
from src.services.order_queue import (
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_RECONCILE_REQUIRED,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_SUBMITTING,
    ORDER_TERMINAL_STATUSES,
    append_order_event,
    can_transition_order_status,
    now_utc,
    transition_order_status,
)
from src.utils.env_vars import get_int_env
from src.utils.ibkr_account import mask_ibkr_account

RECONCILE_ELIGIBLE_STATUSES = {
    ORDER_STATUS_SUBMITTING,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_RECONCILE_REQUIRED,
}


def parse_float(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def make_order_ref(order_id: int) -> str:
    return f"ngtrader-order-{order_id}"


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
        return "filled"
    if value in {"rejected"}:
        return "rejected"
    if value in {"cancelled", "apicancelled", "inactive"}:
        return "cancelled"
    if value in {"submitted", "presubmitted", "pendingsubmit"}:
        if filled_qty > 0:
            return ORDER_STATUS_PARTIALLY_FILLED
        return ORDER_STATUS_SUBMITTED
    if value:
        return ORDER_STATUS_SUBMITTED
    return ORDER_STATUS_QUEUED


def get_cl_min_days_to_expiry() -> int:
    min_days_to_expiry = get_int_env("BROKER_CL_MIN_DAYS_TO_EXPIRY", DEFAULT_CL_MIN_DAYS_TO_EXPIRY)
    if min_days_to_expiry is None or min_days_to_expiry < 0:
        raise ValueError("BROKER_CL_MIN_DAYS_TO_EXPIRY must be >= 0.")
    return min_days_to_expiry


def get_or_qualify_contract(ib: IB, order: Order) -> Contract:
    raw_symbol = (order.symbol or "").strip().upper()
    use_front_month_alias = order.sec_type == "FUT" and raw_symbol.startswith("/")
    symbol = raw_symbol[1:] if use_front_month_alias else raw_symbol
    if not symbol:
        raise RuntimeError(f"Order {order.id} has an invalid symbol '{order.symbol}'.")
    cl_min_days_to_expiry = get_cl_min_days_to_expiry() if symbol == "CL" else None

    if order.con_id:
        contract_kwargs: dict[str, Any] = {
            "conId": order.con_id,
            "symbol": symbol,
            "secType": order.sec_type,
            "exchange": order.exchange,
            "currency": order.currency,
        }
        if order.local_symbol is not None:
            contract_kwargs["localSymbol"] = order.local_symbol
        if order.trading_class is not None:
            contract_kwargs["tradingClass"] = order.trading_class
        contract = Contract(**contract_kwargs)
        qualified = ib.qualifyContracts(contract)
        if len(qualified) == 1:
            qualified_contract = qualified[0]
            if cl_min_days_to_expiry is None:
                return qualified_contract
            days_to_expiry = contract_days_to_expiry(qualified_contract)
            if days_to_expiry is not None and days_to_expiry >= cl_min_days_to_expiry:
                return qualified_contract

    if use_front_month_alias:
        min_days_to_expiry = cl_min_days_to_expiry if cl_min_days_to_expiry is not None else 0
        return select_front_month_future_contract(
            ib,
            symbol=symbol,
            exchange=order.exchange,
            currency=order.currency,
            min_days_to_expiry=min_days_to_expiry,
        )

    if symbol == "CL":
        if cl_min_days_to_expiry is None:
            raise RuntimeError("CL expiry safety window is not configured.")
        return select_front_month_contract(ib, min_days_to_expiry=cl_min_days_to_expiry)

    fallback = Contract(
        symbol=symbol,
        secType=order.sec_type,
        exchange=order.exchange,
        currency=order.currency,
    )
    qualified = ib.qualifyContracts(fallback)
    if len(qualified) != 1:
        raise RuntimeError(f"Could not qualify contract for order {order.id}. If this is a futures front-month intent, submit symbol as '/{symbol}'.")
    return qualified[0]


def _apply_contract_details(order: Order, trade: Trade) -> None:
    contract = trade.contract
    if contract.conId:
        order.con_id = contract.conId
    if contract.localSymbol:
        order.local_symbol = contract.localSymbol
    if contract.tradingClass:
        order.trading_class = contract.tradingClass
    if contract.lastTradeDateOrContractMonth:
        order.contract_expiry = contract.lastTradeDateOrContractMonth


def apply_trade_progress(
    session: Session,
    order: Order,
    trade: Trade,
    *,
    event_type: str,
    message_prefix: str,
) -> bool:
    prev = (
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

    filled_quantity = max(0.0, float(trade.filled() or 0.0))
    normalized_status = normalize_ib_status(trade.orderStatus.status, filled_quantity)
    avg_fill_price = parse_float(trade.orderStatus.avgFillPrice)

    _apply_contract_details(order, trade)
    if trade.order.orderId:
        order.ib_order_id = trade.order.orderId
    if trade.order.permId:
        order.ib_perm_id = trade.order.permId
    order.filled_quantity = filled_quantity
    order.avg_fill_price = avg_fill_price
    order.updated_at = now_utc()

    status_changed = order.status != normalized_status
    emitted_transition_event = False
    if status_changed:
        if can_transition_order_status(order.status, normalized_status):
            transition_order_status(
                session=session,
                order=order,
                next_status=normalized_status,
                event_type=event_type,
                message=(
                    f"{message_prefix}: ib_status={trade.orderStatus.status}, "
                    f"filled={filled_quantity}, remaining={trade.remaining()}, avg_fill={avg_fill_price}"
                ),
            )
            emitted_transition_event = True
        else:
            order.status = normalized_status
            if normalized_status in ORDER_TERMINAL_STATUSES and order.completed_at is None:
                order.completed_at = now_utc()
            session.flush()
            append_order_event(
                session=session,
                order_id=order.id,
                event_type=event_type,
                message=(f"{message_prefix}: forced transition to {normalized_status} from ib_status={trade.orderStatus.status}"),
                status=order.status,
                filled_quantity=order.filled_quantity,
                avg_fill_price=order.avg_fill_price,
                ib_order_id=order.ib_order_id,
            )
    else:
        session.flush()

    current = (
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

    if order.status in ORDER_TERMINAL_STATUSES and order.completed_at is None:
        order.completed_at = now_utc()
        session.flush()

    if not emitted_transition_event:
        append_order_event(
            session=session,
            order_id=order.id,
            event_type=event_type,
            message=(
                f"{message_prefix}: ib_status={trade.orderStatus.status}, filled={filled_quantity}, remaining={trade.remaining()}, avg_fill={avg_fill_price}"
            ),
            status=order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            ib_order_id=order.ib_order_id,
        )
    return True


def process_order(
    ib: IB,
    session: Session,
    order: Order,
    timeout_seconds: float,
) -> None:
    account = session.get(Account, order.account_id)
    if account is None:
        order.status = ORDER_STATUS_FAILED
        order.last_error = f"Missing account row for account_id={order.account_id}"
        order.updated_at = now_utc()
        if order.completed_at is None:
            order.completed_at = now_utc()
        append_order_event(
            session=session,
            order_id=order.id,
            event_type="order_error",
            message=order.last_error or "Missing account row",
            status=order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            ib_order_id=order.ib_order_id,
        )
        return

    try:
        contract = get_or_qualify_contract(ib, order)
        order.con_id = contract.conId
        order.local_symbol = contract.localSymbol
        order.trading_class = contract.tradingClass
        order.contract_expiry = contract.lastTradeDateOrContractMonth
        order.updated_at = now_utc()
        append_order_event(
            session=session,
            order_id=order.id,
            event_type="contract_qualified",
            message=f"Qualified conId={contract.conId}, localSymbol={contract.localSymbol}",
            status=order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            ib_order_id=order.ib_order_id,
        )

        tws_account = account.account
        managed_accounts = ib.managedAccounts()
        if tws_account not in managed_accounts:
            masked = mask_ibkr_account(tws_account)
            raise RuntimeError(f"Account {masked} is not managed by this IBKR session")

        if order.order_type == "LMT":
            if order.limit_price is None:
                raise RuntimeError(f"Order {order.id} has order_type=LMT but no limit_price.")
            ib_order = LimitOrder(order.side, order.quantity, order.limit_price)
        else:
            ib_order = MarketOrder(order.side, order.quantity)
        ib_order.account = tws_account
        ib_order.tif = order.tif
        ib_order.orderRef = make_order_ref(order.id)

        raise RuntimeError("Order execution is not supported at this time.")
        trade = ib.placeOrder(contract, ib_order)
        if order.submitted_at is None:
            order.submitted_at = now_utc()
        apply_trade_progress(
            session=session,
            order=order,
            trade=trade,
            event_type="order_submitted",
            message_prefix="order submitted",
        )
        session.flush()

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline and not trade.isDone():
            ib.waitOnUpdate(timeout=1.0)
            apply_trade_progress(
                session=session,
                order=order,
                trade=trade,
                event_type="order_progress",
                message_prefix="order progress",
            )
            session.flush()

        apply_trade_progress(
            session=session,
            order=order,
            trade=trade,
            event_type="order_final",
            message_prefix="order final",
        )
        if not trade.isDone():
            timeout_message = f"Order timed out after {timeout_seconds:.1f}s waiting for terminal status; marking as failed."
            order.status = ORDER_STATUS_FAILED
            order.last_error = timeout_message
            order.updated_at = now_utc()
            if order.completed_at is None:
                order.completed_at = now_utc()
            append_order_event(
                session=session,
                order_id=order.id,
                event_type="order_timeout",
                message=timeout_message,
                status=order.status,
                filled_quantity=order.filled_quantity,
                avg_fill_price=order.avg_fill_price,
                ib_order_id=order.ib_order_id,
            )

        if trade.advancedError:
            order.last_error = trade.advancedError
            order.updated_at = now_utc()
            append_order_event(
                session=session,
                order_id=order.id,
                event_type="ib_advanced_error",
                message=trade.advancedError,
                status=order.status,
                filled_quantity=order.filled_quantity,
                avg_fill_price=order.avg_fill_price,
                ib_order_id=order.ib_order_id,
            )
    except Exception as exc:
        order.status = ORDER_STATUS_FAILED
        order.last_error = str(exc)
        order.updated_at = now_utc()
        if order.completed_at is None:
            order.completed_at = now_utc()
        append_order_event(
            session=session,
            order_id=order.id,
            event_type="order_error",
            message=f"Worker error: {exc}",
            status=order.status,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            ib_order_id=order.ib_order_id,
        )


def reconcile_open_orders(ib: IB, session: Session) -> int:
    ib.reqOpenOrders()
    ib.waitOnUpdate(timeout=1.0)
    open_trades = list(ib.openTrades())
    trades_by_order_id: dict[int, Trade] = {}
    for trade in open_trades:
        matched_order_id = parse_order_ref(trade.order.orderRef)
        if matched_order_id is not None:
            trades_by_order_id[matched_order_id] = trade

    non_terminal = list(
        session.execute(select(Order).where(Order.status.not_in(tuple(ORDER_TERMINAL_STATUSES))).order_by(Order.created_at.asc())).scalars().all()
    )
    touched = 0
    for order in non_terminal:
        trade = trades_by_order_id.get(order.id)
        if trade is not None:
            changed = apply_trade_progress(
                session=session,
                order=order,
                trade=trade,
                event_type="order_reconciled",
                message_prefix="startup reconciliation",
            )
            touched += 1 if changed else 0
            continue

        if order.status in RECONCILE_ELIGIBLE_STATUSES:
            if order.status != ORDER_STATUS_RECONCILE_REQUIRED:
                transition_order_status(
                    session=session,
                    order=order,
                    next_status=ORDER_STATUS_RECONCILE_REQUIRED,
                    event_type="order_reconcile_required",
                    message="No matching open IB order was found during startup reconciliation.",
                )
            else:
                append_order_event(
                    session=session,
                    order_id=order.id,
                    event_type="order_reconcile_checked",
                    message="No matching open IB order found; remains reconcile_required.",
                    status=order.status,
                    filled_quantity=order.filled_quantity,
                    avg_fill_price=order.avg_fill_price,
                    ib_order_id=order.ib_order_id,
                )
            touched += 1
    return touched
