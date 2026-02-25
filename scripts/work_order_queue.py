"""
Order queue worker.

Polls queued orders, submits them to TWS/Gateway, and stores status/fill progress.
Runs a startup reconciliation pass before claiming new queued orders.

Usage:
  uv run python scripts/work_order_queue.py --env dev
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from typing import Any

from dotenv import load_dotenv
from ib_async import IB, Contract, MarketOrder, Trade
from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Account, Order
from src.services.cl_contracts import (
    DEFAULT_CL_MIN_DAYS_TO_EXPIRY,
    contract_days_to_expiry,
    select_front_month_contract,
)
from src.services.jobs import JOB_TYPE_POSITIONS_SYNC, enqueue_job_if_idle
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
from src.services.worker_heartbeat import WORKER_TYPE_ORDERS, upsert_worker_heartbeat
from src.utils.env_vars import get_int_env
from src.utils.ibkr_account import mask_ibkr_account

logger = logging.getLogger("worker:orders")
RECONCILE_ELIGIBLE_STATUSES = {
    ORDER_STATUS_SUBMITTING,
    ORDER_STATUS_SUBMITTED,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_RECONCILE_REQUIRED,
}


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued orders and execute in TWS.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--client-id", type=int, default=30)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--order-timeout-seconds", type=float, default=45.0)
    parser.add_argument(
        "--connect-timeout-seconds",
        type=float,
        default=20.0,
        help="Timeout for each TWS/Gateway connect attempt.",
    )
    parser.add_argument(
        "--connect-max-attempts",
        type=int,
        default=6,
        help="Number of connect attempts before exiting.",
    )
    parser.add_argument(
        "--connect-retry-seconds",
        type=float,
        default=5.0,
        help="Delay between connect retries.",
    )
    parser.add_argument("--once", action="store_true", help="Process one queue pass and exit.")
    return parser.parse_args()


def check_db_ready() -> None:
    inspector = inspect(get_engine())
    tables = inspector.get_table_names()
    for required in ("accounts", "orders", "order_events", "jobs", "worker_heartbeats"):
        if required not in tables:
            raise SystemExit(f"Missing '{required}' table. Run: task migrate")


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
    cl_min_days_to_expiry = get_cl_min_days_to_expiry() if order.symbol == "CL" else None

    if order.con_id:
        contract_kwargs: dict[str, Any] = {
            "conId": order.con_id,
            "symbol": order.symbol,
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

    if order.symbol == "CL":
        if cl_min_days_to_expiry is None:
            raise RuntimeError("CL expiry safety window is not configured.")
        return select_front_month_contract(ib, min_days_to_expiry=cl_min_days_to_expiry)

    fallback = Contract(
        symbol=order.symbol,
        secType=order.sec_type,
        exchange=order.exchange,
        currency=order.currency,
    )
    qualified = ib.qualifyContracts(fallback)
    if len(qualified) != 1:
        raise RuntimeError(f"Could not qualify contract for order {order.id}")
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
                message=(f"{message_prefix}: forced transition to {normalized_status} from " f"ib_status={trade.orderStatus.status}"),
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
                f"{message_prefix}: ib_status={trade.orderStatus.status}, "
                f"filled={filled_quantity}, remaining={trade.remaining()}, avg_fill={avg_fill_price}"
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

        ib_order = MarketOrder(order.side, order.quantity)
        ib_order.account = tws_account
        ib_order.tif = order.tif
        ib_order.orderRef = make_order_ref(order.id)

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
            timeout_message = f"Order timed out after {timeout_seconds:.1f}s waiting for terminal status; " "marking as failed."
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


def claim_queued_order_for_submission(session: Session, order_id: int) -> Order | None:
    claimed_at = now_utc()
    claim_stmt = (
        update(Order)
        .where(
            Order.id == order_id,
            Order.status == ORDER_STATUS_QUEUED,
        )
        .values(
            status=ORDER_STATUS_SUBMITTING,
            updated_at=claimed_at,
        )
        .returning(Order.id)
    )
    claimed_order_id = session.execute(claim_stmt).scalar_one_or_none()
    if claimed_order_id is None:
        return None
    order = session.get(Order, claimed_order_id)
    if order is None:
        return None
    append_order_event(
        session=session,
        order_id=order.id,
        event_type="order_submitting",
        message="Claimed by worker for broker submission.",
        status=order.status,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        ib_order_id=order.ib_order_id,
    )
    return order


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


def connect_tws_with_retries(
    ib: IB,
    *,
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    timeout_seconds: float,
    max_attempts: int,
    retry_seconds: float,
) -> None:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            ib.connect(host, port, clientId=client_id, timeout=timeout_seconds)
            return
        except TimeoutError:
            last_exc = RuntimeError("Timed out connecting to TWS/Gateway " f"(host={host}, port={port}, client_id={client_id}, timeout={timeout_seconds}s).")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

        details = f"connect attempt {attempt}/{max_attempts} failed: {last_exc}"
        print(details)
        upsert_worker_heartbeat(
            engine,
            WORKER_TYPE_ORDERS,
            status="starting",
            details=details,
        )
        if attempt < max_attempts:
            time.sleep(retry_seconds)

    if last_exc is None:
        raise RuntimeError("Unable to connect to TWS/Gateway and no error details were captured.")
    raise RuntimeError(f"Unable to connect to TWS/Gateway after {max_attempts} attempt(s). Last error: {last_exc}") from last_exc


def run_worker(args: argparse.Namespace) -> int:
    port = args.port if args.port is not None else get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise SystemExit("BROKER_TWS_PORT is not set. Pass --port or set BROKER_TWS_PORT.")

    engine = get_engine()
    ib = IB()
    upsert_worker_heartbeat(
        engine,
        WORKER_TYPE_ORDERS,
        status="starting",
        details=f"connecting to {args.host}:{port}",
    )
    try:
        try:
            connect_tws_with_retries(
                ib,
                engine=engine,
                host=args.host,
                port=port,
                client_id=args.client_id,
                timeout_seconds=args.connect_timeout_seconds,
                max_attempts=args.connect_max_attempts,
                retry_seconds=args.connect_retry_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            message = (
                "Failed to connect to TWS/Gateway after retries. Verify TWS/Gateway is running, " "API access is enabled, and host/port/client-id are correct."
            )
            print(message)
            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_ORDERS,
                status="error",
                details=str(exc),
            )
            return 1

        print(f"Connected to TWS/Gateway at {args.host}:{port}.")
        upsert_worker_heartbeat(
            engine,
            WORKER_TYPE_ORDERS,
            status="running",
            details=f"connected to {args.host}:{port}",
        )

        with Session(engine) as session:
            reconciled = reconcile_open_orders(ib, session)
            session.commit()
        upsert_worker_heartbeat(
            engine,
            WORKER_TYPE_ORDERS,
            status="running",
            details=f"startup reconciliation complete; touched={reconciled}",
        )

        while True:
            processed = 0
            with Session(engine) as session:
                stmt = select(Order.id).where(Order.status == ORDER_STATUS_QUEUED).order_by(Order.created_at.asc()).limit(20)
                order_ids = list(session.execute(stmt).scalars().all())
                for order_id in order_ids:
                    order = claim_queued_order_for_submission(session, order_id)
                    if order is None:
                        continue
                    process_order(
                        ib=ib,
                        session=session,
                        order=order,
                        timeout_seconds=args.order_timeout_seconds,
                    )
                    processed += 1

                if processed > 0:
                    enqueue_job_if_idle(
                        session=session,
                        job_type=JOB_TYPE_POSITIONS_SYNC,
                        payload={},
                        source="worker:orders",
                        request_text="Auto sync after order processing",
                    )
                session.commit()

            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_ORDERS,
                status="running",
                details=f"processed={processed}, tws_connected={ib.isConnected()}",
            )

            if args.once:
                print(f"Processed {processed} order(s).")
                return 0
            if processed == 0:
                time.sleep(args.poll_seconds)
    finally:
        try:
            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_ORDERS,
                status="stopped",
                details="worker exiting",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to persist worker shutdown heartbeat: %s", exc)
        if ib.isConnected():
            ib.disconnect()
            print("Disconnected from TWS/Gateway.")


def main() -> int:
    args = parse_args()
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be > 0.")
    if args.order_timeout_seconds <= 0:
        raise SystemExit("--order-timeout-seconds must be > 0.")
    if args.connect_timeout_seconds <= 0:
        raise SystemExit("--connect-timeout-seconds must be > 0.")
    if args.connect_max_attempts < 1:
        raise SystemExit("--connect-max-attempts must be >= 1.")
    if args.connect_retry_seconds < 0:
        raise SystemExit("--connect-retry-seconds must be >= 0.")

    load_env(args.env)
    check_db_ready()
    return run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
