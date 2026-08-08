"""Sync EOD position snapshots from IBKR FlexQuery into Postgres.

Aggregates LOT-level rows from FlexQuery's OpenPosition section into net
(account, conid) positions and upserts via the uq_account_id_con_id constraint.
Tags rows with data_source='flex' and as_of_date set to the FlexQuery
reportDate (T-1 EOD snapshot).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from defusedxml import ElementTree as ET
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import DateRange
from sqlalchemy import Engine, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Position
from src.services.sync_common import (
    _safe_float,
    _safe_int,
    _safe_str,
    get_or_create_accounts,
)
from src.services.trade_sync_flexquery import FlexTokenExpiredError

logger = logging.getLogger("flex_position_sync")


def _fetch_flex_xml(token: str, query_id: str, start_date: date, end_date: date) -> str:
    from src.services.flex_client_factory import make_flex_client

    client = make_flex_client(span_days=(end_date - start_date).days)
    date_range = DateRange(from_date=start_date, to_date=end_date)
    try:
        return client.fetch_flex_report(token=token, query_id=query_id, date_range=date_range)
    except Exception as exc:
        message = str(exc).lower()
        if "expired" in message or "invalid" in message or "token" in message:
            raise FlexTokenExpiredError(f"FlexQuery token rejected: {exc}") from exc
        raise


def _aggregate_lots(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Aggregate LOT-level rows into net (conid) positions.

    SUM(quantity) for position; weighted average for avg_cost.
    Contract metadata is taken from the first row in each group.
    """
    grouped: list[dict[str, Any]] = []
    for con_id, group in df.groupby("conid", sort=False):
        quantities = group["position"].astype(float)
        costs = group["costBasisPrice"].astype(float) if "costBasisPrice" in group else group.get("costBasis", pd.Series([0.0] * len(group))).astype(float)
        total_qty = float(quantities.sum())
        if total_qty != 0.0:
            avg_cost = float((quantities * costs).sum() / total_qty)
        else:
            avg_cost = 0.0
        first = group.iloc[0]

        # markPrice is per-contract (same across lots); take any non-null.
        mark_price = None
        if "markPrice" in group:
            mark_series = group["markPrice"].dropna()
            if not mark_series.empty:
                mark_price = _safe_float(mark_series.iloc[0])

        # positionValue and fifoPnlUnrealized are per-lot; sum across lots.
        position_value = None
        if "positionValue" in group:
            pv_series = group["positionValue"].astype(float, errors="ignore")
            position_value = float(pv_series.sum()) if len(pv_series) else None

        fifo_pnl_unrealized = None
        if "fifoPnlUnrealized" in group:
            pnl_series = group["fifoPnlUnrealized"].astype(float, errors="ignore")
            fifo_pnl_unrealized = float(pnl_series.sum()) if len(pnl_series) else None

        grouped.append(
            {
                "con_id": _safe_int(con_id),
                "symbol": _safe_str(first.get("symbol")),
                "sec_type": _safe_str(first.get("assetCategory")) or _safe_str(first.get("secType")),
                "exchange": _safe_str(first.get("listingExchange")),
                "primary_exchange": _safe_str(first.get("listingExchange")),
                "currency": _safe_str(first.get("currency")),
                "local_symbol": _safe_str(first.get("localSymbol")) or _safe_str(first.get("symbol")),
                "trading_class": _safe_str(first.get("tradingClass")),
                "last_trade_date": _safe_str(first.get("expiry")),
                "strike": _safe_float(first.get("strike")),
                "right": _safe_str(first.get("putCall")),
                "multiplier": _safe_str(first.get("multiplier")),
                "position": total_qty,
                "avg_cost": avg_cost,
                "mark_price": mark_price,
                "position_value": position_value,
                "fifo_pnl_unrealized": fifo_pnl_unrealized,
            }
        )
    return grouped


def _resolve_as_of_date(df: pd.DataFrame) -> date | None:
    if "reportDate" not in df.columns:
        return None
    series = df["reportDate"].dropna()
    if series.empty:
        return None
    val = series.iloc[0]
    if isinstance(val, pd.Timestamp):
        return val.date()
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    return None


def sync_flex_positions(
    engine: Engine,
    *,
    account_code: str,
    report: CustomFlexReport | None = None,
    flex_token: str | None = None,
    query_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    flex_query_token_id: int | None = None,
) -> dict[str, Any]:
    """Fetch (or accept) FlexQuery open positions for one account and upsert.

    Pass `report` when reusing one fetch across multiple accounts; otherwise
    provide token/query/date_range and this function will fetch its own XML.
    `flex_query_token_id` stamps the account with the token it came from.
    Returns metrics dict with row counts and as_of_date.
    """
    if report is None:
        if not (flex_token and query_id and start_date and end_date):
            raise ValueError("sync_flex_positions: provide either `report` or flex_token+query_id+start_date+end_date")
        xml_data = _fetch_flex_xml(flex_token, query_id, start_date, end_date)
        report = CustomFlexReport()
        report.root = ET.fromstring(xml_data)

    df = report.open_positions_by_account_id(account_code)
    if df is None or len(df.index) == 0:
        logger.info("flex_position_sync: account=%s no positions", account_code)
        return {"upserted_count": 0, "as_of_date": None}

    as_of = _resolve_as_of_date(df)
    aggregated = _aggregate_lots(df)
    now = datetime.now(timezone.utc)

    with Session(engine) as session:
        account_lookup = get_or_create_accounts(session, {account_code}, flex_query_token_id)
        account_id = account_lookup[account_code]

        for row in aggregated:
            stmt = (
                insert(Position)
                .values(
                    account_id=account_id,
                    fetched_at=now,
                    data_source="flex",
                    as_of_date=as_of,
                    **row,
                )
                .on_conflict_do_update(
                    constraint="uq_account_id_con_id",
                    set_={
                        **{k: v for k, v in row.items() if k != "con_id"},
                        "data_source": "flex",
                        "as_of_date": as_of,
                        "fetched_at": now,
                    },
                )
            )
            session.execute(stmt)

        snapshot_con_ids = {row["con_id"] for row in aggregated if row.get("con_id") is not None}
        delete_stmt = delete(Position).where(Position.account_id == account_id)
        if snapshot_con_ids:
            delete_stmt = delete_stmt.where(Position.con_id.notin_(snapshot_con_ids))
        deleted = session.execute(delete_stmt).rowcount

        session.commit()

    logger.info(
        "[flex_position_sync] account=%s as_of=%s rows=%d deleted=%d",
        account_code,
        as_of.isoformat() if as_of else "unknown",
        len(aggregated),
        deleted,
    )
    return {"upserted_count": len(aggregated), "deleted_count": deleted, "as_of_date": as_of}
