"""
Order queue worker.

Polls queued orders, submits them to TWS/Gateway, and stores status/fill progress.
Runs a startup reconciliation pass before claiming new queued orders.

The per-order policy (status normalization, contract qualification, trade
progress, reconciliation) lives in `src/services/order_worker.py`; this script
owns env loading, argparse, the TWS connection, and the claim/poll loop.

Usage:
  uv run python scripts/work_order_queue.py --env dev
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from dotenv import load_dotenv
from ib_async import IB
from sqlalchemy import inspect, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Order
from src.services.jobs import (
    JOB_TYPE_ORDER_FETCH_SYNC,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
    enqueue_job_if_idle,
)
from src.services.order_queue import (
    ORDER_STATUS_QUEUED,
    ORDER_STATUS_SUBMITTING,
    append_order_event,
    now_utc,
)
from src.services.order_worker import process_order, reconcile_open_orders
from src.services.worker_heartbeat import WORKER_TYPE_ORDERS, upsert_worker_heartbeat
from src.utils.env_vars import get_int_env

logger = logging.getLogger("worker:orders")


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued orders and execute in TWS.")
    parser.add_argument("--env", choices=["dev", "prod"], default=None)
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


def connect_tws_with_retries(  # noqa: PLR0913 — retry knobs are explicit CLI-facing parameters
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
            last_exc = RuntimeError(f"Timed out connecting to TWS/Gateway (host={host}, port={port}, client_id={client_id}, timeout={timeout_seconds}s).")
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


def run_worker(args: argparse.Namespace) -> int:  # noqa: C901, PLR0912 — worker loop; one linear connect, reconcile, poll, shutdown sequence
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
                "Failed to connect to TWS/Gateway after retries. Verify TWS/Gateway is running, API access is enabled, and host/port/client-id are correct."
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
                        job_type=JOB_TYPE_ORDER_FETCH_SYNC,
                        payload={},
                        source="worker:orders",
                        request_text="Auto order fetch/sync after order processing",
                    )
                    enqueue_job_if_idle(
                        session=session,
                        job_type=JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
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

    env_name = args.env or os.environ.get("ENV", "dev")
    load_env(env_name)
    check_db_ready()
    return run_worker(args)


if __name__ == "__main__":
    raise SystemExit(main())
