"""
Generic jobs worker.

Polls queued jobs and dispatches handlers by `job_type`.
Initial handler: `positions.sync`

Usage:
  uv run python scripts/work_jobs.py --env dev
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable

from dotenv import load_dotenv
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Job
from src.services.jobs import (
    JOB_TYPE_CONTRACTS_SYNC,
    JOB_TYPE_POSITIONS_SYNC,
    JOB_TYPE_WATCHLIST_ADD_INSTRUMENT,
    JOB_TYPE_WATCHLIST_QUOTES_REFRESH,
    claim_next_job,
    complete_job,
    fail_or_retry_job,
)
from src.services.position_sync import check_positions_tables_ready, sync_positions_once
from src.services.worker_heartbeat import WORKER_TYPE_JOBS, upsert_worker_heartbeat
from src.utils.env_vars import get_int_env

logger = logging.getLogger("worker:jobs")


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued jobs.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--once", action="store_true", help="Process one queue pass and exit.")
    return parser.parse_args()


def check_db_ready() -> None:
    engine = get_engine()
    check_positions_tables_ready(engine)
    tables = inspect(engine).get_table_names()
    for required in ("jobs", "worker_heartbeats"):
        if required not in tables:
            raise SystemExit(f"Missing '{required}' table. Run: task migrate")


def handle_positions_sync(job: Job, engine: Engine) -> dict:
    payload = job.payload or {}
    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")
    connect_timeout_raw = payload.get("connect_timeout_seconds")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = 31

    if isinstance(connect_timeout_raw, (int, float)):
        connect_timeout_seconds = float(connect_timeout_raw)
    else:
        connect_timeout_seconds = 20.0

    fetched_positions_count = sync_positions_once(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    return {
        "fetched_positions_count": fetched_positions_count,
        "host": host,
        "port": port,
        "client_id": client_id,
        "connect_timeout_seconds": connect_timeout_seconds,
    }


def handle_contracts_sync(job: Job, engine: Engine) -> dict:
    from ib_async import Contract, Future

    from src.services.contract_sync import sync_contracts

    payload = job.payload or {}
    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = 32

    # Build contract specs from payload, default to CL futures
    raw_specs = payload.get("specs")
    specs: list[Contract]
    if isinstance(raw_specs, list) and raw_specs:
        specs = []
        for raw in raw_specs:
            if not isinstance(raw, dict):
                continue
            sec_type = raw.get("sec_type", "FUT").upper()
            symbol = raw.get("symbol", "CL")
            exchange = raw.get("exchange", "")
            currency = raw.get("currency", "USD")

            if not exchange:
                raise RuntimeError(f"No exchange specified for {symbol} {sec_type}. " "The job payload must include an exchange.")

            if sec_type == "FUT":
                specs.append(Future(symbol=symbol, exchange=exchange, currency=currency))
            elif sec_type in ("STK", "OPT"):
                specs.append(
                    Contract(
                        symbol=symbol,
                        secType=sec_type,
                        exchange="SMART",
                        currency=currency,
                    )
                )
            else:
                specs.append(
                    Contract(
                        symbol=symbol,
                        secType=sec_type,
                        exchange=exchange,
                        currency=currency,
                    )
                )
        if not specs:
            specs = [Future("CL", exchange="NYMEX", currency="USD")]
    else:
        specs = [Future("CL", exchange="NYMEX", currency="USD")]

    return sync_contracts(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        specs=specs,
    )


def handle_watchlist_add_instrument(job: Job, engine: Engine) -> dict:
    from src.services.watchlist_instrument_sync import fetch_and_add_instrument

    payload = job.payload or {}

    watch_list_id = payload.get("watch_list_id")
    if not isinstance(watch_list_id, int):
        raise ValueError("watchlist.add_instrument job requires integer 'watch_list_id' in payload.")

    symbol = payload.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("watchlist.add_instrument job requires string 'symbol' in payload.")

    sec_type = payload.get("sec_type")
    if not isinstance(sec_type, str) or not sec_type.strip():
        raise ValueError("watchlist.add_instrument job requires string 'sec_type' in payload.")

    exchange = payload.get("exchange")
    if not isinstance(exchange, str) or not exchange.strip():
        raise ValueError("watchlist.add_instrument job requires string 'exchange' in payload.")

    contract_month = payload.get("contract_month")
    if contract_month is not None and not isinstance(contract_month, str):
        raise ValueError("'contract_month' must be a string if provided.")

    strike_raw = payload.get("strike")
    strike = float(strike_raw) if strike_raw is not None else None

    right = payload.get("right")
    if right is not None and not isinstance(right, str):
        raise ValueError("'right' must be a string if provided.")

    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = 34

    return fetch_and_add_instrument(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        watch_list_id=watch_list_id,
        symbol=symbol.strip().upper(),
        sec_type=sec_type.strip().upper(),
        exchange=exchange.strip().upper(),
        contract_month=contract_month,
        strike=strike,
        right=right,
    )


def handle_watchlist_quotes_refresh(job: Job, engine: Engine) -> dict:
    from src.services.watchlist_quotes import refresh_watch_list_quotes

    payload = job.payload or {}
    watch_list_id = payload.get("watch_list_id")
    if not isinstance(watch_list_id, int):
        raise ValueError("watchlist.quotes_refresh job requires integer 'watch_list_id' in payload.")

    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = get_int_env("BROKER_TWS_QUOTES_CLIENT_ID", 141)
    if client_id is None:
        raise RuntimeError("BROKER_TWS_QUOTES_CLIENT_ID is not set and no client_id was provided in job payload.")

    return refresh_watch_list_quotes(
        engine=engine,
        watch_list_id=watch_list_id,
        host=host,
        port=port,
        client_id=client_id,
    )


def get_handler(job_type: str) -> Callable[[Job, Engine], dict] | None:
    handlers: dict[str, Callable[[Job, Engine], dict]] = {
        JOB_TYPE_POSITIONS_SYNC: handle_positions_sync,
        JOB_TYPE_CONTRACTS_SYNC: handle_contracts_sync,
        JOB_TYPE_WATCHLIST_ADD_INSTRUMENT: handle_watchlist_add_instrument,
        JOB_TYPE_WATCHLIST_QUOTES_REFRESH: handle_watchlist_quotes_refresh,
    }
    return handlers.get(job_type)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    load_env(args.env)
    check_db_ready()

    engine = get_engine()
    upsert_worker_heartbeat(
        engine,
        WORKER_TYPE_JOBS,
        status="starting",
        details="worker boot",
    )

    try:
        while True:
            processed = 0
            while True:
                with Session(engine) as session:
                    claimed_job = claim_next_job(session)
                    if claimed_job is None:
                        break
                    job_id = claimed_job.id
                    session.commit()

                processed += 1
                with Session(engine) as session:
                    job = session.get(Job, job_id)
                    if job is None:
                        session.rollback()
                        continue

                    handler = get_handler(job.job_type)
                    if handler is None:
                        logger.warning("job #%d: unsupported job_type '%s'", job_id, job.job_type)
                        fail_or_retry_job(
                            session,
                            job,
                            f"Unsupported job_type '{job.job_type}'",
                            retry_delay_seconds=0,
                        )
                        session.commit()
                        continue

                    logger.info("job #%d: starting %s", job_id, job.job_type)
                    try:
                        result = handler(job, engine)
                        complete_job(session, job, result)
                        logger.info("job #%d: completed %s", job_id, job.job_type)
                    except Exception as exc:
                        fail_or_retry_job(session, job, str(exc))
                        logger.error("job #%d: failed %s — %s", job_id, job.job_type, exc)
                    session.commit()

            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_JOBS,
                status="running",
                details=f"processed={processed}",
            )

            if args.once:
                print(f"Processed {processed} job(s).")
                return 0

            if processed == 0:
                time.sleep(args.poll_seconds)
    finally:
        try:
            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_JOBS,
                status="stopped",
                details="worker exiting",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to persist worker shutdown heartbeat: %s", exc)


if __name__ == "__main__":
    raise SystemExit(main())
