"""
Order stream worker.

Holds the TWS push client ID and writes order changes to the database as TWS
sends them. Off unless ORDER_STREAM_ENABLED is set; enable it on exactly one
machine, because one process may hold the push client ID per TWS.

Usage:
  uv run python scripts/work_order_stream.py --env prod
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

from dotenv import load_dotenv
from sqlalchemy import inspect

from src.db import get_engine
from src.services.order_stream_tws import (
    StreamConfig,
    order_stream_client_id,
    order_stream_enabled,
    run_order_stream,
)
from src.services.worker_heartbeat import (
    WORKER_TYPE_ORDER_STREAM,
    upsert_worker_heartbeat,
)
from src.utils.env_vars import get_int_env

logger = logging.getLogger("worker:order-stream")


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stream TWS order changes into the orders table.")
    parser.add_argument("--env", choices=["dev", "prod"], default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = parse_args()
    load_env(args.env or os.environ.get("ENV", "dev"))

    if not order_stream_enabled():
        logger.info("ORDER_STREAM_ENABLED is not set; the order stream is off. Exiting.")
        return 0

    port = args.port if args.port is not None else get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise SystemExit("BROKER_TWS_PORT is not set. Pass --port or set BROKER_TWS_PORT.")

    engine = get_engine()
    tables = inspect(engine).get_table_names()
    for required in ("orders", "order_events", "jobs", "worker_heartbeats"):
        if required not in tables:
            raise SystemExit(f"Missing '{required}' table. Run: task migrate")

    config = StreamConfig(host=args.host, port=port, client_id=order_stream_client_id())
    logger.info("order stream starting: %s:%s client_id=%s", config.host, config.port, config.client_id)
    try:
        asyncio.run(run_order_stream(engine, config))
    except KeyboardInterrupt:
        pass
    finally:
        try:
            upsert_worker_heartbeat(engine, WORKER_TYPE_ORDER_STREAM, status="stopped", details="worker exiting")
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to persist worker shutdown heartbeat: %s", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
