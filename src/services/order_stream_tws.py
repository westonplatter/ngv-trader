"""Live TWS order stream.

One long-lived session holds the push client ID. TWS order events are coalesced
per order and written through the shared apply path in `order_sync_tws`. After
every connect the full order book is fetched and swept before events are trusted.
The stream only reads: it never places, changes, or cancels a broker order.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from ib_async import IB, StartupFetchNONE, Trade
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Job
from src.services.api_notify import post_to_api
from src.services.jobs import (
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_TYPE_INTRADAY_SYNC_TWS,
    enqueue_job_if_idle,
)
from src.services.order_queue import now_utc
from src.services.order_sync_tws import (
    TradeFetch,
    apply_trade_to_order,
    collect_recent_trades_async,
    find_order_for_trade,
    is_unworked_inactive,
    parse_int,
    reconcile_fetch,
)
from src.services.worker_heartbeat import (
    WORKER_TYPE_ORDER_STREAM,
    upsert_worker_heartbeat,
)
from src.utils.env_vars import get_int_env, get_str_env

logger = logging.getLogger("worker:order-stream")

FILL_SYNC_SOURCE = "worker:order-stream"
CLIENT_ID_IN_USE_ERROR = 326
DATA_LOST_ERRORS = (1101, 1102)
_TRUE_VALUES = {"1", "true", "yes", "on"}

OrderKey = tuple[Any, ...]
NotifyOrder = Callable[[int, str], None]


class StreamState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    RECONCILING = "reconciling"
    LIVE = "live"


@dataclass(frozen=True)
class StreamConfig:
    host: str
    port: int
    client_id: int
    coalesce_seconds: float = 0.25
    connect_timeout_seconds: float = 20.0
    backoff_seconds: float = 5.0
    max_backoff_seconds: float = 60.0
    client_id_in_use_backoff_seconds: float = 30.0
    heartbeat_seconds: float = 5.0


def order_stream_enabled() -> bool:
    value = get_str_env("ORDER_STREAM_ENABLED")
    return value is not None and value.lower() in _TRUE_VALUES


def order_stream_client_id() -> int:
    return get_int_env("ORDER_STREAM_CLIENT_ID", 0)


def notify_order(order_id: int, event: str) -> None:
    post_to_api("/events/notify-order", {"order_id": order_id, "event": event})


def _order_key(trade: Trade) -> OrderKey:
    perm_id = parse_int(getattr(trade.order, "permId", None))
    if perm_id:
        return ("perm", perm_id)
    return ("order", parse_int(getattr(trade.order, "clientId", None)), parse_int(getattr(trade.order, "orderId", None)))


class OrderStreamCore:
    """Stream state, the coalescing writer, the reconcile step, and the fill-sync follow-up."""

    def __init__(
        self,
        engine: Engine,
        *,
        notify: NotifyOrder = notify_order,
        coalesce_seconds: float = 0.25,
        client_id: int | None = None,
    ) -> None:
        self._engine = engine
        self._notify = notify
        self._coalesce_seconds = coalesce_seconds
        self._client_id = client_id
        self._pending: dict[OrderKey, Trade] = {}
        self._wake = asyncio.Event()
        self._resync = asyncio.Event()
        self._fill_lock = asyncio.Lock()
        self._fill_sync_wanted = False
        self._fill_followup = False
        self.state = StreamState.DISCONNECTED
        self.last_event_at: datetime | None = None

    @property
    def resync_requested(self) -> bool:
        return self._resync.is_set()

    def request_resync(self) -> None:
        self._resync.set()

    async def wait_resync(self) -> None:
        await self._resync.wait()

    def reset(self) -> None:
        """Forget events from a previous connection; the next reconcile rebuilds the book."""
        self._pending.clear()
        self._resync.clear()
        self.state = StreamState.DISCONNECTED

    def heartbeat_details(self) -> str:
        last = self.last_event_at.isoformat() if self.last_event_at else None
        return json.dumps({"state": self.state.value, "last_event_at": last, "client_id": self._client_id})

    def on_order_event(self, trade: Trade) -> None:
        key = _order_key(trade)
        self._pending.pop(key, None)
        self._pending[key] = trade
        self.last_event_at = now_utc()
        self._wake.set()

    def on_exec_details(self, trade: Trade, fill: Any) -> None:
        self._fill_sync_wanted = True
        self._wake.set()

    async def reconcile(self, fetch: Callable[[], Awaitable[TradeFetch]]) -> bool:
        """Fetch the full book and sweep it. Events that arrive meanwhile stay queued. True means live."""
        self.state = StreamState.RECONCILING
        started_at = now_utc()
        try:
            fetched = await fetch()
        except Exception:
            logger.exception("order book fetch raised")
            fetched = TradeFetch(trades=[], ok=False)
        if not fetched.ok:
            logger.warning("order book fetch incomplete; no sweep, not going live")
            self.state = StreamState.DISCONNECTED
            return False
        try:
            summary = await asyncio.to_thread(reconcile_fetch, self._engine, fetched, started_at)
        except Exception:
            logger.exception("order book reconcile write failed")
            self.state = StreamState.DISCONNECTED
            return False
        changes = [(order_id, "order.created") for order_id in summary["created_order_ids"]]
        changes += [(order_id, "order.updated") for order_id in summary["updated_order_ids"]]
        await self._notify_changes(changes)
        self.state = StreamState.LIVE
        logger.info("order stream live: fetched=%s changed=%s", summary["fetched_trades_count"], len(changes))
        return True

    def _write_batch(self, trades: list[Trade]) -> list[tuple[int, str]]:
        changes: dict[int, str] = {}
        with Session(self._engine) as session:
            for trade in trades:
                # TWS reports a new order as Inactive for ~100 ms before Submitted.
                if is_unworked_inactive(trade) and find_order_for_trade(session, trade) is None:
                    continue
                result = apply_trade_to_order(session, trade)
                if result.created:
                    changes[result.order.id] = "order.created"
                elif result.changed:
                    changes.setdefault(result.order.id, "order.updated")
            session.commit()
        return list(changes.items())

    async def flush(self) -> None:
        if self.state is not StreamState.LIVE or not self._pending:
            return
        batch = list(self._pending.values())
        self._pending.clear()
        try:
            changes = await asyncio.to_thread(self._write_batch, batch)
        except Exception:
            logger.exception("order event write failed; resyncing")
            self.request_resync()
            return
        await self._notify_changes(changes)

    def _notify_all(self, changes: list[tuple[int, str]]) -> None:
        for order_id, event in changes:
            try:
                self._notify(order_id, event)
            except Exception as exc:
                logger.warning("SSE notify order #%s (%s) failed: %s", order_id, event, exc)

    async def _notify_changes(self, changes: list[tuple[int, str]]) -> None:
        if changes:
            await asyncio.to_thread(self._notify_all, changes)

    def _fill_sync_step(self) -> bool:
        """Queue an intraday run, or note that a running one may have missed the fill. Returns the follow-up flag."""
        with Session(self._engine) as session:
            statuses = set(
                session.execute(
                    select(Job.status).where(
                        Job.job_type == JOB_TYPE_INTRADAY_SYNC_TWS,
                        Job.archived_at.is_(None),
                        Job.status.in_((JOB_STATUS_QUEUED, JOB_STATUS_RUNNING)),
                    )
                )
                .scalars()
                .all()
            )
            followup = False
            if JOB_STATUS_QUEUED in statuses:
                pass
            elif JOB_STATUS_RUNNING in statuses:
                followup = True
            else:
                enqueue_job_if_idle(
                    session,
                    JOB_TYPE_INTRADAY_SYNC_TWS,
                    {},
                    FILL_SYNC_SOURCE,
                    "Fill reported by the order stream.",
                )
            session.commit()
        return followup

    async def service_fill_sync(self) -> None:
        async with self._fill_lock:
            if not (self._fill_sync_wanted or self._fill_followup):
                return
            wanted = self._fill_sync_wanted
            self._fill_sync_wanted = False
            try:
                self._fill_followup = await asyncio.to_thread(self._fill_sync_step)
            except Exception:
                logger.exception("could not queue intraday sync")
                self._fill_sync_wanted = wanted

    async def run_writer(self) -> None:
        while True:
            await self._wake.wait()
            await asyncio.sleep(self._coalesce_seconds)
            self._wake.clear()
            await self.flush()
            await self.service_fill_sync()


@dataclass(frozen=True)
class ConnectionOutcome:
    reached_live: bool
    client_id_in_use: bool


async def _wait_for_loss(core: OrderStreamCore, lost: asyncio.Event, writer: asyncio.Task[None]) -> None:
    waiters = [asyncio.ensure_future(lost.wait()), asyncio.ensure_future(core.wait_resync()), writer]
    try:
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            if not waiter.done():
                waiter.cancel()


async def _run_connection(core: OrderStreamCore, config: StreamConfig) -> ConnectionOutcome:
    ib = IB()
    lost = asyncio.Event()
    in_use = False

    def on_error(req_id: int, code: int, message: str, contract: Any = None) -> None:
        nonlocal in_use
        if code == CLIENT_ID_IN_USE_ERROR:
            in_use = True
        elif code in DATA_LOST_ERRORS:
            logger.warning("TWS reported %s (%s); resyncing", code, message)
            core.request_resync()

    ib.errorEvent += on_error
    ib.disconnectedEvent += lost.set
    core.reset()
    core.state = StreamState.CONNECTING
    writer: asyncio.Task[None] | None = None
    try:
        try:
            await ib.connectAsync(
                config.host,
                config.port,
                clientId=config.client_id,
                timeout=config.connect_timeout_seconds,
                fetchFields=StartupFetchNONE,
            )
        except Exception as exc:
            logger.warning("TWS connect failed (client_id=%s): %s", config.client_id, exc or type(exc).__name__)
            return ConnectionOutcome(reached_live=False, client_id_in_use=in_use)

        if config.client_id == 0:
            ib.reqAutoOpenOrders(True)
        ib.openOrderEvent += core.on_order_event
        ib.orderStatusEvent += core.on_order_event
        ib.execDetailsEvent += core.on_exec_details

        if not await core.reconcile(lambda: collect_recent_trades_async(ib)):
            return ConnectionOutcome(reached_live=False, client_id_in_use=False)

        writer = asyncio.create_task(core.run_writer())
        await _wait_for_loss(core, lost, writer)
        if writer.done() and not writer.cancelled() and writer.exception() is not None:
            logger.error("order stream writer crashed", exc_info=writer.exception())
        logger.warning("order stream lost its session; reconnecting")
        return ConnectionOutcome(reached_live=True, client_id_in_use=False)
    finally:
        if writer is not None and not writer.done():
            writer.cancel()
        if ib.isConnected():
            ib.disconnect()
        core.state = StreamState.DISCONNECTED


async def _heartbeat_loop(engine: Engine, core: OrderStreamCore, interval_seconds: float) -> None:
    while True:
        try:
            await asyncio.to_thread(upsert_worker_heartbeat, engine, WORKER_TYPE_ORDER_STREAM, "running", core.heartbeat_details())
            await core.service_fill_sync()
        except Exception:
            logger.exception("order stream heartbeat failed")
        await asyncio.sleep(interval_seconds)


async def run_order_stream(engine: Engine, config: StreamConfig) -> None:
    """Hold the push client ID forever. A refused ID is retried later; no other ID is ever tried."""
    core = OrderStreamCore(engine, coalesce_seconds=config.coalesce_seconds, client_id=config.client_id)
    heartbeat = asyncio.create_task(_heartbeat_loop(engine, core, config.heartbeat_seconds))
    delay = config.backoff_seconds
    try:
        while True:
            outcome = await _run_connection(core, config)
            if outcome.reached_live:
                delay = config.backoff_seconds
            if outcome.client_id_in_use:
                logger.error(
                    "TWS refused client ID %s as already in use; another process holds it. Retrying in %.0fs.",
                    config.client_id,
                    config.client_id_in_use_backoff_seconds,
                )
                wait = config.client_id_in_use_backoff_seconds
            else:
                wait = delay
                delay = min(delay * 2, config.max_backoff_seconds)
            logger.info("reconnecting in %.0fs", wait)
            await asyncio.sleep(wait)
    finally:
        heartbeat.cancel()
