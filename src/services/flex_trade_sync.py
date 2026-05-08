"""Sync trade executions from IBKR FlexQuery into Postgres.

Fetches trades via ngv_reports_ibkr.FlexClient + CustomFlexReport, upserts into
trade_executions (idempotent on ib_exec_id), resolves parent trades using
ibOrderID grouping (FlexQuery has no permId), and recomputes trade aggregates
from canonical executions.

Writes one flex_sync_log row per call.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import DateRange, FlexClient
from sqlalchemy import Engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Account, FlexSyncLog, Trade, TradeExecution
from src.services.trade_sync import (
    _enforce_canonical_flags,
    _ensure_account,
    _parse_exec_id,
    _recompute_trade_aggregates,
    _safe_float,
    _safe_int,
    _safe_str,
)

logger = logging.getLogger("flex_trade_sync")


class FlexTokenExpiredError(RuntimeError):
    """Raised when the FlexQuery token is expired or invalid."""


_BUY_SELL_NORMALIZATION = {"BOT": "BUY", "SLD": "SELL"}


def previous_business_day(reference: date | None = None) -> date:
    """Return the most recent business day strictly before `reference` (default: today).

    Skips Saturday/Sunday only — does not consult a holiday calendar. FlexQuery
    is T-1 EOD, so the max valid `end_date` is the previous business day.
    """
    cursor = (reference or date.today()) - timedelta(days=1)
    while cursor.weekday() >= 5:  # 5=Sat, 6=Sun
        cursor -= timedelta(days=1)
    return cursor


def _normalize_buy_sell(raw_value: str | None) -> str | None:
    """Strip open/close qualifier and normalize to BUY/SELL.

    Examples: "BUY (O)" -> "BUY", "SELL (C)" -> "SELL", "BOT" -> "BUY".
    Unknown values are returned unchanged with a WARNING log.
    """
    if raw_value is None:
        return None
    base = raw_value.split("(", 1)[0].strip().upper()
    normalized = _BUY_SELL_NORMALIZATION.get(base, base)
    if normalized not in {"BUY", "SELL"}:
        logger.warning("Unrecognized buySell value: %r", raw_value)
    return normalized


def _resolve_or_create_flex_trade(
    session: Session,
    *,
    account_id: int,
    order_ref: str | None,
    ib_order_id: int | None,
    symbol: str | None,
    side: str | None,
    trade_date: str | None,
    now: datetime,
) -> Trade:
    """Find or create a parent Trade row for FlexQuery data.

    FlexQuery has no permId, so tier-1 matching is skipped. Otherwise mirrors
    trade_sync._resolve_or_create_trade: ngtrader-* order_ref match, then
    composite (account_id, ib_order_id, symbol, side, trade_date).
    """
    if order_ref and order_ref.startswith("ngtrader-"):
        existing = (
            session.execute(
                select(Trade).where(
                    Trade.account_id == account_id,
                    Trade.order_ref == order_ref,
                )
            )
            .scalars()
            .first()
        )
        if existing is not None:
            return existing
        trade = Trade(
            account_id=account_id,
            ib_perm_id=None,
            order_ref=order_ref,
            ib_order_id=ib_order_id,
            symbol=symbol,
            side=side,
            status="partial",
            data_source="flex",
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(trade)
        session.flush()
        return trade

    candidates = (
        session.execute(
            select(Trade).where(
                Trade.account_id == account_id,
                Trade.ib_order_id == ib_order_id,
                Trade.symbol == symbol,
                Trade.side == side,
            )
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        if candidate.first_executed_at is not None:
            candidate_date = candidate.first_executed_at.strftime("%Y-%m-%d")
            if candidate_date == trade_date:
                return candidate

    trade = Trade(
        account_id=account_id,
        ib_perm_id=None,
        order_ref=order_ref,
        ib_order_id=ib_order_id,
        symbol=symbol,
        side=side,
        status="partial",
        data_source="flex",
        fetched_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(trade)
    session.flush()
    return trade


def _row_raw(row: pd.Series) -> dict[str, Any]:
    """Serialize a FlexQuery trade row to a JSON-safe dict for audit storage."""
    out: dict[str, Any] = {}
    for key, val in row.items():
        if pd.isna(val):
            out[key] = None
        elif isinstance(val, (pd.Timestamp, datetime)):
            out[key] = val.isoformat()
        elif isinstance(val, (int, float, str, bool)):
            out[key] = val
        else:
            out[key] = str(val)
    return out


def _fetch_flex_xml(token: str, query_id: str, start_date: date, end_date: date) -> str:
    client = FlexClient()
    date_range = DateRange(from_date=start_date, to_date=end_date)
    try:
        return client.fetch_flex_report(token=token, query_id=query_id, date_range=date_range)
    except Exception as exc:  # noqa: BLE001 — surface as typed error
        message = str(exc)
        if "expired" in message.lower() or "invalid" in message.lower() or "token" in message.lower():
            raise FlexTokenExpiredError(f"FlexQuery token rejected: {message}") from exc
        raise


def fetch_flex_report(token: str, query_id: str, start_date: date, end_date: date) -> CustomFlexReport:
    """Fetch and parse a FlexQuery report. Use when you want to dispatch a single
    fetch across multiple accounts (the token returns all linked accounts)."""
    xml_data = _fetch_flex_xml(token, query_id, start_date, end_date)
    report = CustomFlexReport()
    report.root = ET.fromstring(xml_data)
    return report


def sync_flex_trades(
    engine: Engine,
    *,
    account_code: str,
    flex_token: str | None = None,
    query_id: str | None = None,
    start_date: date,
    end_date: date,
    report: CustomFlexReport | None = None,
    skip_aggregate_recompute: bool = False,
) -> dict[str, Any]:
    """Fetch FlexQuery trades for one account in [start_date, end_date] and upsert.

    Args:
        account_code: IBKR account number (e.g. "U1234567"), NOT a friendly alias
        report: Pre-fetched report; when provided, `flex_token`/`query_id` are unused
            (use this when dispatching one fetched report across multiple accounts).
        skip_aggregate_recompute: When True, skip per-trade aggregate recompute
            during ingest. Use during backfill to avoid O(n^2) churn; the caller
            must run recompute_aggregates_for_trades() once at the end.

    Returns metrics dict with counts and window info.
    """
    if report is None and not (flex_token and query_id):
        raise ValueError("sync_flex_trades requires either `report` or both `flex_token` and `query_id`")

    log_id: int | None = None
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        account = _ensure_account(session, account_code)
        log_row = FlexSyncLog(
            account_id=account.id,
            start_date=start_date,
            end_date=end_date,
            status="in_progress",
            fetched_at=now,
        )
        session.add(log_row)
        session.flush()
        log_id = log_row.id
        session.commit()

    if report is None:
        try:
            report = fetch_flex_report(flex_token, query_id, start_date, end_date)
        except FlexTokenExpiredError as exc:
            with Session(engine) as session:
                log_row = session.get(FlexSyncLog, log_id)
                if log_row is not None:
                    log_row.status = "error"
                    log_row.error_message = f"FlexTokenExpiredError: {exc}"
                    session.commit()
            logger.error("FlexQuery token expired/invalid for account=%s: %s", account_code, exc)
            raise
        except Exception as exc:
            with Session(engine) as session:
                log_row = session.get(FlexSyncLog, log_id)
                if log_row is not None:
                    log_row.status = "error"
                    log_row.error_message = f"{type(exc).__name__}: {exc}"
                    session.commit()
            raise

    inserted_count = 0
    canonical_changes = 0
    touched_trade_ids: set[int] = set()
    affected_bases: list[tuple[int, str]] = []
    fetched_count = 0

    with Session(engine) as session:
        account = _ensure_account(session, account_code)
        df = report.trades_by_account_id(account_code)
        if df is None or len(df.index) == 0:
            logger.info("flex_trade_sync: account=%s no trades in range", account_code)
            rows: list[pd.Series] = []
        else:
            rows = [row for _, row in df.iterrows()]
        fetched_count = len(rows)

        for row in rows:
            exec_id = _safe_str(row.get("ibExecID"))
            if not exec_id:
                continue

            exec_time = row.get("dateTime")
            if exec_time is None or pd.isna(exec_time):
                continue
            if isinstance(exec_time, str):
                try:
                    exec_time = datetime.fromisoformat(exec_time)
                except ValueError:
                    continue
            elif isinstance(exec_time, pd.Timestamp):
                exec_time = exec_time.to_pydatetime()
            if exec_time.tzinfo is None:
                exec_time = exec_time.replace(tzinfo=timezone.utc)

            exec_id_base, exec_revision = _parse_exec_id(exec_id)

            ib_order_id = _safe_int(row.get("ibOrderID"))
            order_ref = _safe_str(row.get("orderReference")) or None
            quantity = _safe_float(row.get("quantity")) or 0.0
            price = _safe_float(row.get("tradePrice")) or 0.0
            side = _normalize_buy_sell(_safe_str(row.get("buySell")))
            exchange = _safe_str(row.get("exchange"))
            symbol = _safe_str(row.get("symbol"))
            sec_type = _safe_str(row.get("assetCategory")) or _safe_str(row.get("secType"))
            currency = _safe_str(row.get("currency"))
            commission = _safe_float(row.get("ibCommission"))
            con_id = _safe_int(row.get("conid"))
            flex_transaction_id = _safe_int(row.get("transactionID"))

            trade_date = exec_time.strftime("%Y-%m-%d")

            trade = _resolve_or_create_flex_trade(
                session=session,
                account_id=account.id,
                order_ref=order_ref,
                ib_order_id=ib_order_id,
                symbol=symbol,
                side=side,
                trade_date=trade_date,
                now=now,
            )
            if trade.symbol is None and symbol:
                trade.symbol = symbol
            if trade.sec_type is None and sec_type:
                trade.sec_type = sec_type
            if trade.exchange is None and exchange:
                trade.exchange = exchange
            if trade.currency is None and currency:
                trade.currency = currency

            raw = _row_raw(row)

            stmt = (
                insert(TradeExecution)
                .values(
                    trade_id=trade.id,
                    account_id=account.id,
                    ib_exec_id=exec_id,
                    exec_id_base=exec_id_base,
                    exec_revision=exec_revision,
                    ib_perm_id=None,
                    ib_order_id=ib_order_id,
                    order_ref=order_ref,
                    sec_type=sec_type,
                    con_id=con_id,
                    exec_role="standalone",
                    executed_at=exec_time,
                    quantity=quantity,
                    price=price,
                    side=side,
                    exchange=exchange,
                    currency=currency,
                    liquidity=None,
                    commission=commission,
                    is_canonical=True,
                    data_source="flex",
                    flex_transaction_id=flex_transaction_id,
                    raw=raw,
                    fetched_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["ib_exec_id"],
                    set_={
                        "trade_id": trade.id,
                        "quantity": quantity,
                        "price": price,
                        "commission": commission,
                        "sec_type": sec_type,
                        "con_id": con_id,
                        "exec_role": "standalone",
                        "data_source": "flex",
                        "flex_transaction_id": flex_transaction_id,
                        "raw": raw,
                        "fetched_at": now,
                        "updated_at": now,
                    },
                )
            )
            result = session.execute(stmt)
            if getattr(result, "rowcount", None) == 1:
                inserted_count += 1

            affected_bases.append((account.id, exec_id_base))
            touched_trade_ids.add(trade.id)

        for acct_id, base in affected_bases:
            canonical_changes += _enforce_canonical_flags(session, acct_id, base)

        if not skip_aggregate_recompute:
            for trade_id in touched_trade_ids:
                _recompute_trade_aggregates(session, trade_id, now)

        log_row = session.get(FlexSyncLog, log_id)
        if log_row is not None:
            log_row.status = "success"
            log_row.row_count = fetched_count
        session.commit()

    metrics = {
        "fetched_executions_count": fetched_count,
        "inserted_executions_count": inserted_count,
        "canonical_changes_count": canonical_changes,
        "touched_trade_ids": sorted(touched_trade_ids),
        "touched_trades_count": len(touched_trade_ids),
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "flex_sync_log_id": log_id,
    }
    logger.info(
        "[flex_trade_sync] account=%s start=%s end=%s rows=%d status=success",
        account_code,
        start_date.isoformat(),
        end_date.isoformat(),
        fetched_count,
    )
    return metrics


def recompute_aggregates_for_trades(
    engine: Engine,
    trade_ids: list[int] | set[int],
) -> None:
    """Recompute parent trade aggregates for a set of trade ids.

    Used by backfill flow that calls sync_flex_trades(skip_aggregate_recompute=True)
    and defers recompute until after all chunks are ingested.
    """
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        for trade_id in trade_ids:
            _recompute_trade_aggregates(session, trade_id, now)
        session.commit()
