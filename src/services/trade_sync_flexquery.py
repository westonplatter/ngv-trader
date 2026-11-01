"""Sync trade executions from IBKR FlexQuery into Postgres.

Fetches trades via ngv_reports_ibkr.FlexClient + CustomFlexReport, normalizes the
EXECUTION rows into fills, and hands them to the shared ingest
(``src/services/fill_ingest.py``), which resolves parent trades, upserts
``trade_executions`` (idempotent on ``ib_exec_id``), synthesizes the
``combo_summary`` row for each multi-leg spread, and recomputes trade aggregates
from canonical executions.

Writes one flex_sync_log row per call.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd
from defusedxml import ElementTree as ET
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.models import FlexSyncLog
from src.services.fill_ingest import FLEX_SOURCE, NormalizedFill, ingest_fills, normalize_side
from src.services.flex_client_factory import FlexTokenExpiredError, fetch_flex_xml
from src.services.group_link_carryover import carry_over_settled_group_links
from src.services.live_reconcile import reconcile_orphaned_live_executions
from src.services.sync_common import (
    _ensure_account,
    _recompute_trade_aggregates,
    _safe_float,
    _safe_int,
    _safe_str,
)
from src.utils.ibkr_account import mask_ibkr_account

logger = logging.getLogger("flex_trade_sync")


def previous_business_day(reference: date | None = None) -> date:
    """Return the most recent business day strictly before `reference` (default: today).

    Skips Saturday/Sunday only — does not consult a holiday calendar. FlexQuery
    is T-1 EOD, so the max valid `end_date` is the previous business day.
    """
    cursor = (reference or date.today()) - timedelta(days=1)
    while cursor.weekday() >= 5:  # 5=Sat, 6=Sun
        cursor -= timedelta(days=1)
    return cursor


def _combo_groups(rows: list[pd.Series]) -> dict[str, list[int]]:
    """Group EXECUTION rows by brokerageOrderID. Return only genuine multi-leg combos.

    Returns {brokerageOrderID: [row_index_in_rows_list]}.
    Rows with empty/blank brokerageOrderID are skipped (treated as solo).

    A shared brokerageOrderID alone is NOT enough to call a group a combo: a single
    single-instrument order frequently fills in several executions (e.g. 10 shares as
    9 + 1). Those are partial fills of one contract, not legs of a spread, and must not
    get a synthetic combo_summary — that row's `signed_cash / gcd(qty)` price degrades to
    raw notional (10 × 400 = 4000) instead of a per-unit price.

    A real combo spans ≥2 distinct contracts, so require ≥2 distinct (non-null) conids.
    Flex always reports conid; if a group's conids are all missing we can't distinguish a
    spread from partial fills, so we conservatively do NOT treat it as a combo.
    """
    groups: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        bid = _safe_str(row.get("brokerageOrderID"))
        if not bid:
            continue
        groups.setdefault(bid, []).append(idx)

    def _is_multi_leg(idxs: list[int]) -> bool:
        if len(idxs) < 2:
            return False
        conids = {_safe_int(rows[i].get("conid")) for i in idxs}
        conids.discard(None)
        return len(conids) >= 2

    return {bid: idxs for bid, idxs in groups.items() if _is_multi_leg(idxs)}


def _row_raw(row: pd.Series) -> dict[str, Any]:
    """Serialize a FlexQuery trade row to a JSON-safe dict for audit storage.

    Also emits a TWS-compatible `contract` sub-dict so display helpers like
    `contract_display_from_raw` (which expect raw["contract"]["symbol"], etc.)
    work uniformly for TWS- and FlexQuery-sourced executions.
    """
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

    # Synthesize a TWS-shaped contract sub-dict for the display layer.
    # FlexQuery flat fields → ib_async Contract field names.
    sec_type = out.get("assetCategory") or out.get("secType")
    out["contract"] = {
        "conId": out.get("conid"),
        "symbol": out.get("underlyingSymbol") or out.get("symbol"),
        "secType": sec_type,
        "exchange": out.get("exchange") or out.get("listingExchange"),
        "currency": out.get("currency"),
        "localSymbol": out.get("symbol"),  # FlexQuery's `symbol` is the OCC/local symbol
        "lastTradeDateOrContractMonth": out.get("expiry"),
        "strike": out.get("strike"),
        "right": out.get("putCall"),
        "tradingClass": None,
        "multiplier": out.get("multiplier"),
    }
    return out


def _row_exec_time(row: pd.Series) -> datetime | None:
    """The fill's timestamp, tz-aware, or ``None`` when the row carries none."""
    exec_time = row.get("dateTime")
    if exec_time is None or pd.isna(exec_time):
        return None
    if isinstance(exec_time, str):
        try:
            exec_time = datetime.fromisoformat(exec_time)
        except ValueError:
            return None
    elif isinstance(exec_time, pd.Timestamp):
        exec_time = exec_time.to_pydatetime()
    if exec_time.tzinfo is None:
        exec_time = exec_time.replace(tzinfo=timezone.utc)
    return exec_time


def flex_rows_to_fills(rows: list[pd.Series], account_code: str) -> list[NormalizedFill]:
    """Normalize one account's EXECUTION rows into fills for the shared ingest.

    Rows without a timestamp are skipped. A BookTrade row (assignment, exercise,
    expiration) carries no ``ibExecID`` but a unique Flex ``transactionID``, so
    it gets a sentinel exec id; the unique partial index on
    ``flex_transaction_id`` keeps it idempotent. Multi-leg combos are tagged
    with their ``brokerageOrderID`` so the ingest shares one ``BAG`` parent
    across the legs and synthesizes the summary row; the parent's symbol is the
    most common underlying across the legs (mirrors TWS, which carries the
    underlying on the BAG fill).
    """
    combo_groups = _combo_groups(rows)
    combo_key_by_idx = {idx: bid for bid, idxs in combo_groups.items() for idx in idxs}
    underlying_by_combo: dict[str, str | None] = {}
    for bid, idxs in combo_groups.items():
        underlyings = [u for i in idxs for u in [_safe_str(rows[i].get("underlyingSymbol"))] if u]
        underlying_by_combo[bid] = max(set(underlyings), key=underlyings.count) if underlyings else None

    fills: list[NormalizedFill] = []
    for idx, row in enumerate(rows):
        exec_id = _safe_str(row.get("ibExecID"))
        if not exec_id:
            book_txn_id = _safe_int(row.get("transactionID"))
            if book_txn_id is None:
                continue
            exec_id = f"FLEX-TX-{book_txn_id}"
        exec_time = _row_exec_time(row)
        if exec_time is None:
            continue
        combo_key = combo_key_by_idx.get(idx)
        fills.append(
            NormalizedFill(
                account_code=account_code,
                ib_exec_id=exec_id,
                executed_at=exec_time,
                quantity=_safe_float(row.get("quantity")) or 0.0,
                price=_safe_float(row.get("tradePrice")) or 0.0,
                side=normalize_side(_safe_str(row.get("buySell"))),
                symbol=_safe_str(row.get("symbol")),
                sec_type=_safe_str(row.get("assetCategory")) or _safe_str(row.get("secType")),
                con_id=_safe_int(row.get("conid")),
                exchange=_safe_str(row.get("exchange")),
                currency=_safe_str(row.get("currency")),
                commission=_safe_float(row.get("ibCommission")),
                raw=_row_raw(row),
                ib_perm_id=None,  # FlexQuery has no permId
                ib_order_id=_safe_int(row.get("ibOrderID")),
                order_ref=_safe_str(row.get("orderReference")) or None,
                flex_transaction_id=_safe_int(row.get("transactionID")),
                combo_key=combo_key,
                combo_underlying=underlying_by_combo.get(combo_key) if combo_key else None,
            )
        )
    return fills


def fetch_flex_report(token: str, query_id: str, start_date: date, end_date: date) -> CustomFlexReport:
    """Fetch and parse a FlexQuery report. Use when you want to dispatch a single
    fetch across multiple accounts (the token returns all linked accounts)."""
    xml_data = fetch_flex_xml(token, query_id, start_date, end_date)
    report = CustomFlexReport()
    report.root = ET.fromstring(xml_data)
    return report


def _mark_log_error(engine: Engine, log_id: int | None, message: str) -> None:
    with Session(engine) as session:
        log_row = session.get(FlexSyncLog, log_id)
        if log_row is not None:
            log_row.status = "error"
            log_row.error_message = message
            session.commit()


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
    flex_query_token_id: int | None = None,
) -> dict[str, Any]:
    """Fetch FlexQuery trades for one account in [start_date, end_date] and upsert.

    Args:
        account_code: IBKR account number (e.g. "U1234567"), NOT a friendly alias
        report: Pre-fetched report; when provided, `flex_token`/`query_id` are unused
            (use this when dispatching one fetched report across multiple accounts).
        skip_aggregate_recompute: When True, skip per-trade aggregate recompute
            during ingest. Use during backfill to avoid O(n^2) churn; the caller
            must run recompute_aggregates_for_trades() once at the end.
        flex_query_token_id: The token this report came from; stamped onto the
            account row so the token-to-account mapping is recorded.

    Returns metrics dict with counts and window info.
    """
    if report is None and not (flex_token and query_id):
        raise ValueError("sync_flex_trades requires either `report` or both `flex_token` and `query_id`")

    masked_account = mask_ibkr_account(account_code)
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
            _mark_log_error(engine, log_id, f"FlexTokenExpiredError: {exc}")
            logger.error("FlexQuery token expired/invalid for account=%s: %s", masked_account, exc)
            raise
        except Exception as exc:
            _mark_log_error(engine, log_id, f"{type(exc).__name__}: {exc}")
            raise

    with Session(engine) as session:
        # Stamp the owning token here rather than in the log-row transaction
        # above, so a sync that fails leaves no stamp behind.
        _ensure_account(session, account_code, flex_query_token_id)
        df = report.trades_by_account_id(account_code)
        if df is None or len(df.index) == 0:
            logger.info("flex_trade_sync: account=%s no trades in range", masked_account)
            rows: list[pd.Series] = []
        else:
            # Restrict to EXECUTION level — other levels (SUMMARY, LOT, etc.) carry
            # no ibExecID and are not individual fills.
            df = df.query("levelOfDetail == 'EXECUTION'") if "levelOfDetail" in df.columns else df
            rows = [row for _, row in df.iterrows()]
        fetched_count = len(rows)

        result = ingest_fills(
            session,
            flex_rows_to_fills(rows, account_code),
            source=FLEX_SOURCE,
            now=now,
            skip_aggregate_recompute=skip_aggregate_recompute,
        )

        # Transition any preemptive live trade-group tags onto the fills that
        # just settled (keyed by ib_exec_id), so grouping survives the
        # live→settled handoff even when the intraday overlay isn't running.
        carried_group_links = carry_over_settled_group_links(session)

        # Purge orphaned live fills whose settled twin exists under a DIFFERENT
        # ib_exec_id (combo-leg id normalization; expiration/assignment book
        # events), which the id-equality carry-over above cannot see, plus live
        # BAG combo summaries whose legs have settled. Prevents phantom
        # "unsettled" rows and intraday realized-P&L double-counts.
        reconciled = reconcile_orphaned_live_executions(session)

        log_row = session.get(FlexSyncLog, log_id)
        if log_row is not None:
            log_row.status = "success"
            log_row.row_count = fetched_count
        session.commit()

    metrics = {
        "fetched_executions_count": fetched_count,
        "inserted_executions_count": result.inserted,
        "canonical_changes_count": result.canonical_changes,
        "combo_summaries_count": result.combo_summaries,
        "touched_trade_ids": sorted(result.touched_trade_ids),
        "touched_trades_count": len(result.touched_trade_ids),
        "carried_group_links_count": carried_group_links,
        "reconciled_orphan_live_count": reconciled["leg_strip"] + reconciled["book_event"] + reconciled["bag_summary"],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "flex_sync_log_id": log_id,
    }
    logger.info(
        "[flex_trade_sync] account=%s start=%s end=%s rows=%d combos=%d status=success",
        masked_account,
        start_date.isoformat(),
        end_date.isoformat(),
        fetched_count,
        result.combo_summaries,
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
