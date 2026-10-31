"""Sync trade executions from IBKR TWS into Postgres.

Fetches fills via ib_async, normalizes them, and hands them to the shared
ingest (``src/services/fill_ingest.py``), which resolves parent trades, upserts
``trade_executions`` (idempotent on ``ib_exec_id``), enforces canonical revision
flags, and recomputes trade aggregates from canonical executions.

Dormant: not registered with the jobs worker while FlexQuery is the active
path (see docs/design/workers.md). Kept so re-enabling is a one-line change.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ib_async import IB, ExecutionFilter
from sqlalchemy import Engine, inspect
from sqlalchemy.orm import Session

from src.services.fill_ingest import TWS_SOURCE, NormalizedFill, ingest_fills, normalize_side
from src.services.sync_common import _safe_float, _safe_int, _safe_str

logger = logging.getLogger("trade_sync")


def check_trades_tables_ready(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for required in ("trades", "trade_executions", "accounts"):
        if required not in tables:
            raise RuntimeError(f"'{required}' table does not exist. Run: task migrate")


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


def _fill_exec_time(execution: Any) -> datetime | None:
    exec_time = getattr(execution, "time", None)
    if exec_time is None:
        return None
    if isinstance(exec_time, str):
        try:
            exec_time = datetime.fromisoformat(exec_time)
        except ValueError:
            return None
    if exec_time.tzinfo is None:
        exec_time = exec_time.replace(tzinfo=timezone.utc)
    return exec_time


def tws_fills_to_fills(fills: list[Any], window_start: datetime) -> list[NormalizedFill]:
    """Normalize ``ib.fills()`` into fills for the shared ingest.

    Skips fills with no execution, exec id, timestamp, or account, and fills
    older than ``window_start``. A ``BAG`` fill is the spread's own summary; its
    legs arrive as plain fills under the same permId and are re-tagged by the
    ingest once the summary is on the trade.
    """
    normalized: list[NormalizedFill] = []
    for fill in fills:
        execution = getattr(fill, "execution", None)
        if execution is None:
            continue
        exec_id = getattr(execution, "execId", None)
        if not exec_id:
            continue
        exec_time = _fill_exec_time(execution)
        if exec_time is None or exec_time < window_start:
            continue
        account_code = str(getattr(execution, "acctNumber", "") or "").strip()
        if not account_code:
            continue

        contract = getattr(fill, "contract", None)
        sec_type = _safe_str(getattr(contract, "secType", None)) if contract else None
        comm_report = getattr(fill, "commissionReport", None)
        normalized.append(
            NormalizedFill(
                account_code=account_code,
                ib_exec_id=exec_id,
                executed_at=exec_time,
                quantity=_safe_float(getattr(execution, "shares", None)) or 0.0,
                price=_safe_float(getattr(execution, "price", None)) or 0.0,
                side=normalize_side(_safe_str(getattr(execution, "side", None))),
                symbol=_safe_str(getattr(contract, "symbol", None)) if contract else None,
                sec_type=sec_type,
                con_id=_safe_int(getattr(contract, "conId", None)) if contract else None,
                exchange=_safe_str(getattr(execution, "exchange", None)),
                currency=_safe_str(getattr(contract, "currency", None)) if contract else None,
                commission=_safe_float(getattr(comm_report, "commission", None)) if comm_report else None,
                raw=_fill_to_raw(fill),
                ib_perm_id=_safe_int(getattr(execution, "permId", None)),
                ib_order_id=_safe_int(getattr(execution, "orderId", None)),
                order_ref=_safe_str(getattr(execution, "orderRef", None)),
                liquidity=_safe_str(getattr(execution, "liquidation", None)),
                is_combo_summary=sec_type == "BAG",
            )
        )
    return normalized


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

    with Session(engine) as session:
        result = ingest_fills(session, tws_fills_to_fills(fills, window_start), source=TWS_SOURCE, now=now)
        session.commit()

    return {
        "fetched_executions_count": len(fills),
        "inserted_executions_count": result.inserted,
        "updated_executions_count": result.updated,
        "canonical_changes_count": result.canonical_changes,
        "touched_trades_count": len(result.touched_trade_ids),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
    }
