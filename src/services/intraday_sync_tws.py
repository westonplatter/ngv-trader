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
from datetime import datetime, timedelta, timezone
from numbers import Real
from typing import Any
from zoneinfo import ZoneInfo

from ib_async import IB
from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import (
    ContractRef,
    LatestQuote,
    LiveExecution,
    LivePosition,
    TradeExecution,
)
from src.services.contract_sync import _upsert_contract
from src.services.group_link_carryover import (
    carry_over_link_to_execution,
    carry_over_settled_group_links,
)
from src.services.sync_common import get_or_create_accounts

logger = logging.getLogger(__name__)

BATCH_SIZE = 100

# The trading "day" boundary for "today's fills" is the exchange trade date, in
# US-Eastern (exchange time), regardless of server timezone.
MARKET_TZ = ZoneInfo("America/New_York")

# CME's trade date opens at 18:00 ET and runs to 17:00 ET the next day, so a fill
# at 19:00 ET Monday belongs to Tuesday's trade date. Anchoring the intraday
# window here (rather than at ET midnight) keeps it aligned with the trade date
# IBKR itself assigns — which is both what ``reqExecutions`` returns as "the
# current trading day" and how FlexQuery later files the fill.
SESSION_OPEN_HOUR_ET = 18


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    parsed = float(value)
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _safe_int(value: object) -> int | None:
    parsed = _safe_float(value)
    return int(parsed) if parsed is not None else None


def session_start_utc(now: datetime | None = None) -> datetime:
    """UTC instant the current exchange trade date opened (most recent 18:00 ET).

    Used as the lower bound for "today's" fills. ``now`` is for testability.

    Previously anchored at ET midnight, which disagreed with the exchange by six
    hours in the worst direction: a fill between 18:00 and 24:00 ET belongs to
    the *next* trade date, so the overlay filed it under the current calendar day
    and then dropped it at ET midnight — while FlexQuery, which files it under
    the next trade date, would not report it for another full day. Evening fills
    were therefore recoverable for only ~6 hours, then invisible for ~30.

    Re-including the prior evening's fills is safe: ``_write_fills`` upserts on
    ``ib_exec_id`` and ``_purge_settled`` drops anything that has since settled.
    """
    now = now or _now_utc()
    et_now = now.astimezone(MARKET_TZ)
    session_open = et_now.replace(hour=SESSION_OPEN_HOUR_ET, minute=0, second=0, microsecond=0)
    if et_now < session_open:
        # Before 18:00 ET we are still inside the session that opened yesterday.
        session_open -= timedelta(days=1)
    return session_open.astimezone(timezone.utc)


def select_mark(bid: float | None, ask: float | None, last: float | None, close: float | None) -> float | None:
    """Mark-selection rule, defined once and reused.

    ``last`` if present; else midpoint ``(bid+ask)/2`` when both sides exist;
    else ``close``. Returns ``None`` when no usable price exists.

    IBKR returns ``-1`` (and sometimes ``0``) as a "no market data" sentinel for
    bid/ask/last/close — common after the close or without a data subscription.
    Any non-positive value is treated as missing so a position is never marked
    off the sentinel.
    """
    last = last if (last is not None and last > 0) else None
    bid = bid if (bid is not None and bid > 0) else None
    ask = ask if (ask is not None and ask > 0) else None
    close = close if (close is not None and close > 0) else None
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


def _sync_held_contract_magnifiers(session: Session, ib: IB, held_contracts: list, now: datetime) -> int:
    """Ensure every held instrument has a ``contracts`` row with a price magnifier.

    ``ib.positions()`` returns plain contracts (no ``priceMagnifier``), and many
    held con_ids — grains, livestock, etc. — are never touched by the per-symbol
    contract-chain sync, so the overlay's magnifier lookup misses them and live
    P&L is computed in the wrong price unit. Here we fetch ``reqContractDetails``
    (which carries the authoritative ``priceMagnifier``) and upsert each into the
    security master. Only con_ids that don't already have a magnifier are
    fetched, so steady-state runs add zero IB round-trips. Returns the count
    upserted.
    """
    held_by_con_id = {c.conId: c for c in held_contracts if getattr(c, "conId", None)}
    if not held_by_con_id:
        return 0
    have = set(
        session.execute(
            select(ContractRef.con_id).where(
                ContractRef.con_id.in_(list(held_by_con_id)),
                ContractRef.price_magnifier.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    needed = [c for con_id, c in held_by_con_id.items() if con_id not in have]
    upserted = 0
    for contract in needed:
        try:
            details = ib.reqContractDetails(contract)
        except Exception:
            logger.exception("reqContractDetails failed for held con_id %s", contract.conId)
            continue
        for detail in details:
            cid = _upsert_contract(
                session,
                detail,
                contract.symbol,
                contract.secType,
                contract.exchange,
                contract.currency,
                underlying_con_id=None,
                now=now,
            )
            if cid is not None:
                upserted += 1
    return upserted


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


def _order_group_key(execution: Any) -> tuple[str, int] | None:
    """Key grouping a combo's BAG summary fill with its leg fills.

    Prefers ``permId`` (stable across the order lifecycle), falling back to
    ``orderId``. ``None`` when the fill carries neither — such fills stay
    ``standalone`` rather than being grouped by a weaker signal.
    """
    perm_id = _safe_int(getattr(execution, "permId", None))
    if perm_id:
        return ("perm", perm_id)
    order_id = _safe_int(getattr(execution, "orderId", None))
    if order_id:
        return ("order", order_id)
    return None


def _exec_roles_by_exec_id(fills: list) -> dict[str, str]:
    """Resolve COMBO/LEG roles across one ``ib.fills()`` batch.

    The intraday feed delivers a combo order as one ``BAG`` summary fill plus
    one fill per leg, all sharing an order key. Within each order group, the BAG
    fill becomes ``combo_summary`` and its non-BAG siblings become ``leg``;
    everything else stays ``standalone``.

    Mirrors the settled path (``trade_sync_tws._retag_combo_roles``) but computes
    the roles in-memory over the current batch, keeping the intraday sync
    self-contained and idempotent on ``ib_exec_id``. Like FlexQuery's
    ``_combo_groups``, a group must span at least 2 distinct leg conIds to
    qualify — so a lone BAG fill or a single-leg order is not mislabeled.
    """
    groups: dict[tuple[str, int], list[Any]] = {}
    for fill in fills:
        execution = getattr(fill, "execution", None)
        exec_id = getattr(execution, "execId", None) if execution else None
        if not exec_id:
            continue
        key = _order_group_key(execution)
        if key is None:
            continue
        groups.setdefault(key, []).append(fill)

    roles: dict[str, str] = {}
    for group_fills in groups.values():
        bag_fills = [f for f in group_fills if _fill_sec_type(f) == "BAG"]
        leg_fills = [f for f in group_fills if _fill_sec_type(f) != "BAG"]
        leg_con_ids = {cid for f in leg_fills if (cid := _fill_con_id(f)) is not None}
        if not bag_fills or len(leg_con_ids) < 2:
            continue
        for fill in bag_fills:
            roles[fill.execution.execId] = "combo_summary"
        for fill in leg_fills:
            roles[fill.execution.execId] = "leg"
    return roles


def _fill_sec_type(fill: Any) -> str | None:
    contract = getattr(fill, "contract", None)
    return getattr(contract, "secType", None) if contract else None


def _fill_con_id(fill: Any) -> int | None:
    contract = getattr(fill, "contract", None)
    return _safe_int(getattr(contract, "conId", None)) if contract else None


def _live_execution_values(
    fill: Any,
    account_id: int,
    exec_time: datetime,
    now: datetime,
    exec_role: str = "standalone",
) -> dict:
    execution = fill.execution
    contract = getattr(fill, "contract", None)
    return {
        "ib_exec_id": execution.execId,
        "account_id": account_id,
        "ib_perm_id": _safe_int(getattr(execution, "permId", None)),
        "ib_order_id": _safe_int(getattr(execution, "orderId", None)),
        "exec_role": exec_role,
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


def _fetch_fills(ib: IB) -> list:
    """Today's fills, re-requested from TWS rather than read from session cache.

    ``ib.fills()`` returns only the *session* cache: the snapshot ib_async takes
    at connect, plus whatever arrives afterwards on ``execDetails``. TWS pushes
    ``execDetails`` only to the client that placed the order — manually-entered
    orders go to client id 0 alone — so with the worker's own client id, a
    manual fill placed *after* connect never reaches the long-lived pooled
    session and stays invisible until it settles via FlexQuery.

    ``reqExecutions`` with a default filter re-asks for all of the current day's
    executions regardless of client id (it is the same call that builds the
    connect-time snapshot) and refreshes the wrapper cache as a side effect. One
    extra round-trip per sync; ``_write_fills`` is idempotent on ``ib_exec_id``.
    """
    try:
        return ib.reqExecutions()
    except Exception:
        logger.exception("reqExecutions failed; falling back to the session fill cache")
        return ib.fills()


def _fetch_positions(ib: IB) -> list:
    """Current positions, read from the wrapper cache.

    Deliberately *not* ``reqPositions``. Unlike executions, positions are not
    client-scoped: ``connect`` subscribes via ``reqPositionsAsync`` and TWS pushes
    every subsequent update to the cache, so it self-heals within a second or two.
    ``reqPositions`` would buy a sub-second freshness gain and pay for it twice —
    its result list is appended to unconditionally, so it (a) returns closed
    ``position == 0`` rows that the cache pops, which would resurrect net-closed
    positions as phantom flat rows, and (b) can carry the same ``conId`` twice when
    an update lands mid-request, violating ``uq_live_positions_account_id_con_id``
    and rolling back the whole sync. The cache is a dict keyed by conId, so it is
    structurally immune to both.

    Freshness comes from *when* this is called instead: see ``run_intraday_sync``.
    """
    return ib.positions()


def _write_fills(
    session: Session,
    fills: list,
    account_lookup: dict[str, int],
    window_start: datetime,
    now: datetime,
) -> int:
    """Upsert today's fills into live_executions, keyed by ib_exec_id."""
    written = 0
    # Roles are resolved across the whole batch first: a fill's COMBO/LEG role
    # depends on its siblings, not on the fill alone.
    roles = _exec_roles_by_exec_id(fills)
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

        vals = _live_execution_values(
            fill,
            account_lookup[account_code],
            exec_time,
            now,
            exec_role=roles.get(execution.execId, "standalone"),
        )
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


def _settled_combo_summaries(session: Session) -> dict[str, int]:
    """Map live BAG ``ib_exec_id`` -> settled ``trade_executions.id`` for the same combo.

    TWS reports a combo's BAG summary under an ``execId`` of its own, drawn from
    a different id family than its legs. FlexQuery, by contrast, synthesizes the
    settled summary *from* the legs. The two rows describe the same fill but can
    never share an ``ib_exec_id``, so the id-equality purge cannot retire the
    live one: the legs settle and disappear while the summary lingers, and the
    combo shows twice in the UI — once ``unsettled``, once ``filled``.

    Match on identity instead: same account, same instant, both BAG. Two distinct
    combos filling on one account within the same second is not worth
    distinguishing — both live rows are superseded either way. Matching on price
    or side would be wrong: TWS may report a combo as several partial BAG fills
    that FlexQuery reports netted into one, and the two sides disagree on sign.

    Recomputed on every sync, so a summary that settles between runs still gets
    retired rather than having to be caught in the one run where its legs did.
    """
    live_bags = session.execute(
        select(LiveExecution.ib_exec_id, LiveExecution.account_id, LiveExecution.exec_time).where(LiveExecution.sec_type == "BAG")
    ).all()
    if not live_bags:
        return {}
    settled = session.execute(
        select(TradeExecution.account_id, TradeExecution.executed_at, TradeExecution.id).where(
            TradeExecution.sec_type == "BAG",
            TradeExecution.executed_at.in_({exec_time for _, _, exec_time in live_bags}),
        )
    ).all()
    settled_by_key = {(account_id, executed_at): trade_execution_id for account_id, executed_at, trade_execution_id in settled}
    return {
        ib_exec_id: trade_execution_id
        for ib_exec_id, account_id, exec_time in live_bags
        if (trade_execution_id := settled_by_key.get((account_id, exec_time))) is not None
    }


def _purge_settled(session: Session) -> int:
    """Drop live fills that have since settled (settled wins).

    A live fill counts as settled two ways: an exact ``ib_exec_id`` match — legs
    and standalone fills, whose ids TWS and FlexQuery agree on — and the
    combo-summary identity match in ``_settled_combo_summaries`` for BAG rows,
    whose ids they do not.

    Carries any live trade-group assignment over to the settled execution first.
    """
    settled_ids = set(session.execute(select(TradeExecution.ib_exec_id).where(TradeExecution.ib_exec_id.in_(select(LiveExecution.ib_exec_id)))).scalars())
    combo_summaries = _settled_combo_summaries(session)
    if not settled_ids and not combo_summaries:
        return 0
    carry_over_settled_group_links(session, settled_ids)
    for live_exec_id, trade_execution_id in combo_summaries.items():
        # Ids differ across the handoff, so the id-equality carry-over above
        # cannot see these — resolve each one explicitly.
        carry_over_link_to_execution(session, live_exec_id, trade_execution_id)
    purge_ids = settled_ids | set(combo_summaries)
    return session.execute(delete(LiveExecution).where(LiveExecution.ib_exec_id.in_(purge_ids))).rowcount or 0


def run_intraday_sync(engine: Engine, ib: IB) -> dict:
    """Fetch positions, marks, and today's fills; write the three live tables.

    The IB session is provided by the caller (worker pool), matching
    ``market_data.fetch_snapshot``. Returns counts
    ``{positions, quotes, fills, purged}``.
    """
    now = _now_utc()
    window_start = session_start_utc(now)

    # Fills first, positions second: TWS updates its position book a moment after
    # it reports an execution, so the positions snapshot must be the *newer* of
    # the two. Reading positions first (with the slow ticker fetch in between)
    # meant a fill could be recorded while the position it created was still
    # missing, leaving a tagged trade whose position never surfaced in its group.
    fills = _fetch_fills(ib)

    # Current positions = authoritative current state, covering every held
    # instrument including ones opened today — no ContractRef-cache dependency.
    # Position contracts carry a conId but no exchange, so qualify them to fill
    # the exchange before requesting market data.
    positions = _fetch_positions(ib)
    held_contracts = [p.contract for p in positions if getattr(p.contract, "conId", None)]
    held_contracts = _ensure_market_data_exchange(ib, held_contracts)
    tickers_by_con_id = _fetch_tickers(ib, held_contracts)

    # Re-read the cache now that the slow ticker fetch is done: TWS pushed any
    # position update that landed during it, and this snapshot is what gets
    # written. Free (no round-trip). Marks stay keyed off the earlier read — a
    # position opened in the gap lands without a mark and degrades to settled.
    positions = _fetch_positions(ib)
    position_accounts = {p.account for p in positions if getattr(p, "account", None)}

    with Session(engine) as session:
        account_lookup = get_or_create_accounts(session, position_accounts) if position_accounts else {}
        counts = {
            "contracts": _sync_held_contract_magnifiers(session, ib, held_contracts, now),
            "positions": _write_live_positions(session, positions, account_lookup, now),
            "quotes": _write_quotes(session, tickers_by_con_id, now),
            "fills": _write_fills(session, fills, account_lookup, window_start, now),
        }
        counts["purged"] = _purge_settled(session)
        session.commit()

    logger.info("Intraday sync complete: %s", counts)
    return counts
