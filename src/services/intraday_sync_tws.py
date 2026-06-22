"""Intraday TWS overlay sync: current positions, live marks, today's fills.

One IB session does all three fetches and writes the three live-overlay tables
(`live_positions`, `latest_quote`, `live_executions`). The FlexQuery `positions`
/ `trade_executions` tables are never touched — this is an additive live layer.

Source of truth for current state is ``ib.positions()`` (authoritative current
quantity + TWS-blended average cost), so the four intraday mutation cases
(open / add / reduce / net-close) fall out without lot arithmetic. Fills drive
*realized* attribution only, never quantity.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from numbers import Real
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import LatestQuote, LiveExecution, LivePosition, TradeExecution
from src.services.sync_common import get_or_create_accounts

logger = logging.getLogger(__name__)

BATCH_SIZE = 100

# The trading "day" boundary for "today's fills" is the US-Eastern session date
# (exchange time), regardless of server timezone. Fills at/after ET midnight of
# the current ET date are considered intraday.
MARKET_TZ = ZoneInfo("America/New_York")


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def session_start_utc(now: datetime | None = None) -> datetime:
    """UTC instant of ET-midnight for the current ET session date.

    Used as the lower bound for "today's" fills. ``now`` is for testability.
    """
    now = now or _now_utc()
    et_now = now.astimezone(MARKET_TZ)
    et_midnight = et_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return et_midnight.astimezone(timezone.utc)


def select_mark(bid: float | None, ask: float | None, last: float | None, close: float | None) -> float | None:
    """Mark-selection rule, defined once and reused.

    ``last`` if present; else midpoint ``(bid+ask)/2`` when both sides exist;
    else ``close``. Returns ``None`` when no usable price exists (the read-time
    merge then degrades to the FlexQuery snapshot mark).
    """
    if last is not None:
        return last
    if bid is not None and ask is not None:
        return (bid + ask) / 2.0
    return close


def _parse_exec_time(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fill_realized_pnl(fill: Any) -> float | None:
    """Realized P&L for a live fill from its commissionReport (TWS shape)."""
    report = getattr(fill, "commissionReport", None)
    if report is None:
        return None
    return _safe_float(getattr(report, "realizedPNL", None))


# Sec types that route market data through SMART when no exchange is set.
SMART_ROUTED_SEC_TYPES = {"STK", "OPT", "CASH", "IND", "CFD"}


def _ensure_market_data_exchange(ib: IB, contracts: list) -> list:
    """Populate a usable ``exchange`` on held contracts before ``reqTickers``.

    ``ib.positions()`` returns contracts with a ``conId`` but a blank
    ``exchange``, which ``reqTickers`` rejects (IB warning 321). ``qualifyContracts``
    round-trips the conId to fill the correct exchange — futures get their real
    exchange (NYMEX/CME/CFE/…), index options get CBOE, etc. Any contract still
    missing an exchange falls back to SMART (equity-style) or its primary
    exchange.
    """
    if not contracts:
        return []
    qualified: list = []
    for i in range(0, len(contracts), BATCH_SIZE):
        batch = contracts[i : i + BATCH_SIZE]
        try:
            qualified.extend(ib.qualifyContracts(*batch))
        except Exception:
            logger.exception("qualifyContracts failed for a batch of %d held contracts", len(batch))
            qualified.extend(batch)
    for c in qualified:
        if not getattr(c, "exchange", None):
            c.exchange = "SMART" if c.secType in SMART_ROUTED_SEC_TYPES else getattr(c, "primaryExchange", None)
    return qualified


def _fetch_tickers(ib: IB, contracts: list) -> dict[int, Any]:
    """Request snapshot tickers in batches; return mapping con_id → ticker."""
    total = len(contracts)
    if total == 0:
        return {}
    batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
    logger.info("Fetching tickers for %d held contracts (%d batches)", total, batches)
    ib.reqMarketDataType(3)  # delayed-frozen if live unavailable
    by_con_id: dict[int, Any] = {}
    for i in range(0, total, BATCH_SIZE):
        batch = contracts[i : i + BATCH_SIZE]
        tickers = ib.reqTickers(*batch)
        for ticker in tickers:
            contract = getattr(ticker, "contract", None)
            con_id = getattr(contract, "conId", None)
            if isinstance(con_id, int) and con_id > 0:
                by_con_id[con_id] = ticker
    logger.info("Received %d/%d tickers", len(by_con_id), total)
    return by_con_id


def _write_live_positions(session: Session, positions: list, account_lookup: dict[str, int], now: datetime) -> int:
    """Replace live_positions for the fetched account scope with fresh rows.

    Clearing prior rows for these accounts then inserting fresh makes
    net-closed positions (absent from ``ib.positions()``) disappear.
    """
    scope_account_ids = set(account_lookup.values())
    if scope_account_ids:
        session.execute(delete(LivePosition).where(LivePosition.account_id.in_(scope_account_ids)))

    written = 0
    for p in positions:
        account_id = account_lookup.get(p.account)
        if account_id is None:
            continue
        contract = p.contract
        session.add(
            LivePosition(
                account_id=account_id,
                con_id=contract.conId,
                symbol=contract.symbol,
                sec_type=contract.secType,
                local_symbol=contract.localSymbol,
                multiplier=contract.multiplier,
                right=contract.right,
                strike=contract.strike if contract.strike else None,
                position=p.position,
                avg_cost=p.avgCost,
                fetched_at=now,
            )
        )
        written += 1
    return written


def _write_quotes(session: Session, tickers_by_con_id: dict[int, Any], now: datetime) -> int:
    """Upsert one latest_quote row per held con_id (newest-wins)."""
    written = 0
    for con_id, ticker in tickers_by_con_id.items():
        bid = _safe_float(getattr(ticker, "bid", None))
        ask = _safe_float(getattr(ticker, "ask", None))
        last = _safe_float(getattr(ticker, "last", None))
        close = _safe_float(getattr(ticker, "close", None))
        vals = {
            "con_id": con_id,
            "bid": bid,
            "ask": ask,
            "last": last,
            "close": close,
            "mark": select_mark(bid, ask, last, close),
            "market_ts": now,
            "ingested_at": now,
        }
        session.execute(
            insert(LatestQuote)
            .values(**vals)
            .on_conflict_do_update(
                index_elements=["con_id"],
                set_={k: v for k, v in vals.items() if k != "con_id"},
            )
        )
        written += 1
    return written


def _live_execution_values(fill: Any, account_id: int, exec_time: datetime, now: datetime) -> dict:
    execution = fill.execution
    contract = getattr(fill, "contract", None)
    return {
        "ib_exec_id": execution.execId,
        "account_id": account_id,
        "con_id": getattr(contract, "conId", None) if contract else None,
        "symbol": getattr(contract, "symbol", None) if contract else None,
        "sec_type": getattr(contract, "secType", None) if contract else None,
        "local_symbol": getattr(contract, "localSymbol", None) if contract else None,
        "multiplier": getattr(contract, "multiplier", None) if contract else None,
        "right": getattr(contract, "right", None) if contract else None,
        "strike": _safe_float(getattr(contract, "strike", None)) if contract else None,
        "side": getattr(execution, "side", None),
        "quantity": _safe_float(getattr(execution, "shares", None)) or 0.0,
        "price": _safe_float(getattr(execution, "price", None)) or 0.0,
        "realized_pnl": _fill_realized_pnl(fill),
        "exec_time": exec_time,
        "fetched_at": now,
    }


def _write_fills(session: Session, fills: list, account_lookup: dict[str, int], window_start: datetime, now: datetime) -> int:
    """Upsert today's fills into live_executions, keyed by ib_exec_id."""
    written = 0
    for fill in fills:
        execution = getattr(fill, "execution", None)
        if execution is None or not getattr(execution, "execId", None):
            continue
        exec_time = _parse_exec_time(getattr(execution, "time", None))
        if exec_time is None or exec_time < window_start:
            continue
        account_code = str(getattr(execution, "acctNumber", "") or "").strip()
        if not account_code:
            continue
        # Ensure account exists even if it had no open position this run.
        if account_code not in account_lookup:
            account_lookup.update(get_or_create_accounts(session, {account_code}))

        vals = _live_execution_values(fill, account_lookup[account_code], exec_time, now)
        session.execute(
            insert(LiveExecution)
            .values(**vals)
            .on_conflict_do_update(
                index_elements=["ib_exec_id"],
                set_={k: v for k, v in vals.items() if k != "ib_exec_id"},
            )
        )
        written += 1
    return written


def _purge_settled(session: Session) -> int:
    """Drop live fills whose ib_exec_id has since settled (settled wins)."""
    settled_ids = set(session.execute(select(TradeExecution.ib_exec_id).where(TradeExecution.ib_exec_id.in_(select(LiveExecution.ib_exec_id)))).scalars())
    if not settled_ids:
        return 0
    return session.execute(delete(LiveExecution).where(LiveExecution.ib_exec_id.in_(settled_ids))).rowcount or 0


def run_intraday_sync(engine: Engine, ib: IB) -> dict:
    """Fetch positions, marks, and today's fills; write the three live tables.

    The IB session is provided by the caller (worker pool), matching
    ``market_data.fetch_snapshot``. Returns counts
    ``{positions, quotes, fills, purged}``.
    """
    now = _now_utc()
    window_start = session_start_utc(now)

    # Current positions = authoritative current state, covering every held
    # instrument including ones opened today — no ContractRef-cache dependency.
    # ib.positions() contracts carry a conId but no exchange, so qualify them to
    # fill the exchange before requesting market data.
    positions = ib.positions()
    position_accounts = {p.account for p in positions if getattr(p, "account", None)}
    held_contracts = [p.contract for p in positions if getattr(p.contract, "conId", None)]
    held_contracts = _ensure_market_data_exchange(ib, held_contracts)
    tickers_by_con_id = _fetch_tickers(ib, held_contracts)
    fills = ib.fills()

    with Session(engine) as session:
        account_lookup = get_or_create_accounts(session, position_accounts) if position_accounts else {}
        counts = {
            "positions": _write_live_positions(session, positions, account_lookup, now),
            "quotes": _write_quotes(session, tickers_by_con_id, now),
            "fills": _write_fills(session, fills, account_lookup, window_start, now),
        }
        counts["purged"] = _purge_settled(session)
        session.commit()

    logger.info("Intraday sync complete: %s", counts)
    return counts
