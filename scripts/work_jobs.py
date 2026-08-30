"""
Generic jobs worker — CLI entrypoint.

Polls queued jobs and dispatches handlers by `job_type`. Handler definitions
and the dispatch table live in `src/workers/jobs.py`; this script owns env
loading, argparse, the polling loop, and worker heartbeat lifecycle.

Usage:
  uv run python scripts/work_jobs.py --env dev
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from dotenv import load_dotenv
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Job
from src.services.jobs import (
    JOB_TYPE_POSITIONS_FLEXQUERY_FETCH_REPORT,
    JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
    JOB_TYPE_TRADES_SYNC_TWS,
    JobDeferred,
    claim_next_job,
    complete_job,
    defer_job,
    fail_or_retry_job,
)
from src.services.position_sync_tws import check_positions_tables_ready
from src.services.worker_heartbeat import WORKER_TYPE_JOBS, upsert_worker_heartbeat
from src.workers.jobs import IBSessionPool, get_handler

logger = logging.getLogger("worker:jobs")

# ---------------------------------------------------------------------------
# SSE notification helper — best-effort POST to the API process so that
# job state transitions reach SSE subscribers in real time.
# ---------------------------------------------------------------------------

_API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")


def _notify_api(path: str, payload: dict) -> None:
    """Fire-and-forget POST to an API notification endpoint."""
    import json
    import urllib.request

    url = f"{_API_BASE_URL}{path}"
    if not url.startswith(("http://", "https://")):
        return
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=2)  # nosec B310


def _notify_job_event(job_id: int, event: str = "job.updated") -> None:
    """Fire-and-forget notification to the API SSE broadcaster."""
    try:
        _notify_api("/events/notify-job", {"job_id": job_id, "event": event})
        logger.debug("SSE notify job #%d (%s) OK", job_id, event)
    except Exception as exc:
        logger.warning("SSE notify job #%d failed: %s", job_id, exc)


# Job types that actually write trade/position rows. The `*.sync.flexquery`
# entrypoints only fan out child jobs and commit no data, so notifying on them
# would fire before the statement is collected — `*.flexquery.fetch_report` is
# the phase that ingests.
_TRADE_WRITING_JOB_TYPES = frozenset(
    {
        JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
        JOB_TYPE_TRADES_SYNC_TWS,
    }
)
_POSITION_WRITING_JOB_TYPES = frozenset(
    {
        JOB_TYPE_POSITIONS_FLEXQUERY_FETCH_REPORT,
    }
)


def _notify_coarse_for_job_type(job_type: str) -> None:
    """Publish coarse trade/position SSE events when matching sync jobs finish."""
    try:
        if job_type in _TRADE_WRITING_JOB_TYPES:
            _notify_api("/events/notify-trades", {})
        elif job_type in _POSITION_WRITING_JOB_TYPES:
            _notify_api("/events/notify-positions", {})
    except Exception as exc:
        logger.warning("SSE coarse notify for %s failed: %s", job_type, exc)


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process queued jobs.")
    parser.add_argument("--env", choices=["dev", "prod"], default=None)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--ib-idle-seconds", type=float, default=300.0, help="Disconnect pooled IB sessions idle for this many seconds.")
    parser.add_argument("--once", action="store_true", help="Process one queue pass and exit.")
    return parser.parse_args()


def check_db_ready() -> None:
    engine = get_engine()
    check_positions_tables_ready(engine)
    tables = inspect(engine).get_table_names()
    for required in ("jobs", "worker_heartbeats"):
        if required not in tables:
            raise SystemExit(f"Missing '{required}' table. Run: task migrate")


def main() -> int:
    args = parse_args()
    if args.poll_seconds <= 0:
        raise SystemExit("--poll-seconds must be > 0.")
    if args.ib_idle_seconds < 0:
        raise SystemExit("--ib-idle-seconds must be >= 0.")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    env_name = args.env or os.environ.get("ENV", "dev")
    load_env(env_name)
    check_db_ready()

    engine = get_engine()
    upsert_worker_heartbeat(
        engine,
        WORKER_TYPE_JOBS,
        status="starting",
        details="worker boot",
    )

    ib_pool = IBSessionPool()
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
                _notify_job_event(job_id, "job.updated")

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
                        _notify_job_event(job_id, "job.updated")
                        continue

                    logger.info("job #%d: starting %s", job_id, job.job_type)
                    job_type_str = job.job_type
                    completed_ok = False
                    try:
                        result = handler(job, engine, ib_pool)
                        complete_job(session, job, result)
                        completed_ok = True
                        logger.info("job #%d: completed %s", job_id, job_type_str)
                    except JobDeferred as deferred:
                        # Not a failure — the handler is waiting on something
                        # slow and asked to run again shortly. Requeue without
                        # spending an attempt.
                        defer_job(session, job, deferred.reason, deferred.retry_after_seconds)
                        logger.info(
                            "job #%d: deferred %s for %ds — %s",
                            job_id,
                            job_type_str,
                            deferred.retry_after_seconds,
                            deferred.reason,
                        )
                    except Exception as exc:
                        fail_or_retry_job(session, job, str(exc))
                        logger.error("job #%d: failed %s — %s", job_id, job_type_str, exc)
                    session.commit()
                    _notify_job_event(job_id, "job.updated")
                    if completed_ok:
                        _notify_coarse_for_job_type(job_type_str)

            upsert_worker_heartbeat(
                engine,
                WORKER_TYPE_JOBS,
                status="running",
                details=f"processed={processed}, ib_sessions={ib_pool.active_count()}",
            )

            if args.once:
                print(f"Processed {processed} job(s).")
                return 0

            ib_pool.close_idle(max_idle_seconds=args.ib_idle_seconds)
            if processed == 0:
                time.sleep(args.poll_seconds)
    finally:
        ib_pool.close_all()
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
