"""Sync EOD position snapshots from IBKR FlexQuery into Postgres.

Aggregates LOT-level rows from FlexQuery's OpenPosition section into net
(account, conid) positions and upserts via the uq_account_id_con_id constraint.
Tags rows with data_source='flex' and as_of_date set to the FlexQuery
reportDate (T-1 EOD snapshot).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import DateRange, FlexClient
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Position
from src.services.flex_trade_sync import FlexTokenExpiredError
from src.services.position_sync import get_or_create_accounts
from src.services.trade_sync import _safe_float, _safe_int, _safe_str

logger = logging.getLogger("flex_position_sync")


def _fetch_flex_xml(token: str, query_id: str, start_date: date, end_date: date) -> str:
    client = FlexClient()
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
    flex_token: str,
    query_id: str,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Fetch FlexQuery open positions for one account and upsert.

    Returns metrics dict with row counts and as_of_date.
    """
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
        account_lookup = get_or_create_accounts(session, {account_code})
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

        session.commit()

    logger.info(
        "[flex_position_sync] account=%s as_of=%s rows=%d",
        account_code,
        as_of.isoformat() if as_of else "unknown",
        len(aggregated),
    )
    return {"upserted_count": len(aggregated), "as_of_date": as_of}
