"""Sync trade executions from IBKR FlexQuery into Postgres.

Fetches trades via ngv_reports_ibkr.FlexClient + CustomFlexReport, upserts into
trade_executions (idempotent on ib_exec_id), resolves parent trades using
ibOrderID grouping (FlexQuery has no permId), and recomputes trade aggregates
from canonical executions.

Writes one flex_sync_log row per call.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from functools import reduce
from math import gcd
from typing import Any

import pandas as pd
from defusedxml import ElementTree as ET
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import DateRange
from sqlalchemy import Engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import FlexSyncLog, Trade, TradeExecution
from src.services.group_link_carryover import carry_over_settled_group_links
from src.services.sync_common import (
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

    # FlexQuery `ib_order_id` uniquely identifies an IBKR order, so the composite
    # `(account_id, ib_order_id, symbol, side)` is sufficient for parent dedup.
    # We do NOT add a trade_date check because timezone normalization between the
    # DataFrame's exec_time and the persisted `first_executed_at` can disagree
    # at the day boundary, causing duplicate parents on re-runs.
    existing = (
        session.execute(
            select(Trade)
            .where(
                Trade.account_id == account_id,
                Trade.ib_order_id == ib_order_id,
                Trade.symbol == symbol,
                Trade.side == side,
            )
            .order_by(Trade.id.asc())
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
    `_contract_display_from_raw` (which expect raw["contract"]["symbol"], etc.)
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


def _fetch_flex_xml(token: str, query_id: str, start_date: date, end_date: date) -> str:
    from src.services.flex_client_factory import make_flex_client

    client = make_flex_client()
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
            logger.error(
                "FlexQuery token expired/invalid for account=%s: %s",
                f"{account_code[:3]}***{account_code[-2:]}" if len(account_code) >= 5 else "***",
                exc,
            )
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
    combo_count = 0

    with Session(engine) as session:
        account = _ensure_account(session, account_code)
        df = report.trades_by_account_id(account_code)
        if df is None or len(df.index) == 0:
            logger.info(
                "flex_trade_sync: account=%s no trades in range",
                f"{account_code[:3]}***{account_code[-2:]}" if len(account_code) >= 5 else "***",
            )
            rows: list[pd.Series] = []
        else:
            # Restrict to EXECUTION level — other levels (SUMMARY, LOT, etc.) carry
            # no ibExecID and are not individual fills.
            df = df.query("levelOfDetail == 'EXECUTION'") if "levelOfDetail" in df.columns else df
            rows = [row for _, row in df.iterrows()]
        fetched_count = len(rows)

        # Pre-pass: identify multi-leg combo groups by brokerageOrderID
        combo_groups = _combo_groups(rows)
        combo_idx_to_bid: dict[int, str] = {idx: bid for bid, idxs in combo_groups.items() for idx in idxs}
        # Cache: brokerageOrderID -> shared parent Trade (created on first leg)
        parent_trade_by_combo: dict[str, Trade] = {}

        for idx, row in enumerate(rows):
            exec_id = _safe_str(row.get("ibExecID"))
            if not exec_id:
                # BookTrade rows (assignments/exercises/expirations) carry no
                # ibExecID but have a unique Flex transactionID. Synthesize a
                # sentinel ib_exec_id so they get persisted; the unique partial
                # index on flex_transaction_id provides idempotency.
                book_txn_id = _safe_int(row.get("transactionID"))
                if book_txn_id is None:
                    continue
                exec_id = f"FLEX-TX-{book_txn_id}"

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

            combo_bid = combo_idx_to_bid.get(idx)
            if combo_bid is not None:
                # Multi-leg combo leg — share one Trade parent across all legs of this brokerageOrderID
                trade = parent_trade_by_combo.get(combo_bid)
                if trade is None:
                    # Tier-0 dedup: re-attach to existing parent created by a prior sync run.
                    # Combo summaries store brokerageOrderID in raw["brokerage_order_id"].
                    # `raw` is JSON (not JSONB), so use json_extract_path_text.
                    existing_combo = (
                        session.execute(
                            select(TradeExecution)
                            .where(
                                TradeExecution.account_id == account.id,
                                TradeExecution.exec_role == "combo_summary",
                                func.json_extract_path_text(TradeExecution.raw, "brokerage_order_id") == combo_bid,
                            )
                            .limit(1)
                        )
                        .scalars()
                        .first()
                    )
                    if existing_combo is not None:
                        trade = session.get(Trade, existing_combo.trade_id)
                    if trade is None:
                        # Derive parent symbol from the most-common underlyingSymbol across legs
                        # (mirrors TWS BAG behavior, which carried the underlying like "AAPL").
                        leg_indices = combo_groups[combo_bid]
                        underlyings = [_safe_str(rows[i].get("underlyingSymbol")) for i in leg_indices]
                        underlyings = [u for u in underlyings if u]
                        parent_symbol = max(set(underlyings), key=underlyings.count) if underlyings else None
                        trade = Trade(
                            account_id=account.id,
                            ib_perm_id=None,
                            order_ref=order_ref,
                            ib_order_id=None,
                            symbol=parent_symbol,
                            sec_type="BAG",
                            side=None,
                            status="partial",
                            data_source="flex",
                            fetched_at=now,
                            created_at=now,
                            updated_at=now,
                        )
                        session.add(trade)
                        session.flush()
                    parent_trade_by_combo[combo_bid] = trade
                exec_role = "leg"
            else:
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
                exec_role = "standalone"

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
                    exec_role=exec_role,
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
                        "exec_role": exec_role,
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

        # Synthesize a combo_summary execution per multi-leg combo group
        for combo_bid, leg_indices in combo_groups.items():
            parent_trade = parent_trade_by_combo.get(combo_bid)
            if parent_trade is None:
                continue
            inserted = _synthesize_combo_summary(
                session=session,
                account_id=account.id,
                parent_trade_id=parent_trade.id,
                parent_symbol=parent_trade.symbol,
                brokerage_order_id=combo_bid,
                leg_rows=[rows[i] for i in leg_indices],
                now=now,
            )
            if inserted is not None:
                combo_count += 1
                if inserted.get("inserted"):
                    inserted_count += 1
                affected_bases.append((account.id, inserted["exec_id_base"]))
                touched_trade_ids.add(parent_trade.id)

        for acct_id, base in affected_bases:
            canonical_changes += _enforce_canonical_flags(session, acct_id, base)

        if not skip_aggregate_recompute:
            for trade_id in touched_trade_ids:
                _recompute_trade_aggregates(session, trade_id, now)

        # Transition any preemptive live trade-group tags onto the fills that
        # just settled (keyed by ib_exec_id), so grouping survives the
        # live→settled handoff even when the intraday overlay isn't running.
        carried_group_links = carry_over_settled_group_links(session)

        log_row = session.get(FlexSyncLog, log_id)
        if log_row is not None:
            log_row.status = "success"
            log_row.row_count = fetched_count
        session.commit()

    metrics = {
        "fetched_executions_count": fetched_count,
        "inserted_executions_count": inserted_count,
        "canonical_changes_count": canonical_changes,
        "combo_summaries_count": combo_count,
        "touched_trade_ids": sorted(touched_trade_ids),
        "touched_trades_count": len(touched_trade_ids),
        "carried_group_links_count": carried_group_links,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "flex_sync_log_id": log_id,
    }
    masked_account = f"{account_code[:3]}***{account_code[-2:]}" if len(account_code) >= 5 else "***"
    logger.info(
        "[flex_trade_sync] account=%s start=%s end=%s rows=%d combos=%d status=success",
        masked_account,
        start_date.isoformat(),
        end_date.isoformat(),
        fetched_count,
        combo_count,
    )
    return metrics


def _synthesize_combo_summary(
    session: Session,
    *,
    account_id: int,
    parent_trade_id: int,
    parent_symbol: str | None,
    brokerage_order_id: str,
    leg_rows: list[pd.Series],
    now: datetime,
) -> dict[str, Any] | None:
    """Upsert a synthetic combo_summary execution row for a multi-leg combo.

    Idempotent: keyed on `ib_exec_id = f"{brokerage_order_id}.combo"`.
    Returns metadata dict (with `inserted: bool` and `exec_id_base`) or None on skip.
    """
    if len(leg_rows) < 2:
        return None

    quantities: list[float] = []
    signed_cash = 0.0
    commissions: list[float] = []
    earliest: datetime | None = None
    leg_exec_ids: list[str] = []
    order_refs: list[str] = []
    currencies: set[str] = set()
    exchanges: set[str] = set()

    for row in leg_rows:
        qty = _safe_float(row.get("quantity")) or 0.0
        px = _safe_float(row.get("tradePrice")) or 0.0
        quantities.append(qty)
        signed_cash += qty * px
        comm = _safe_float(row.get("ibCommission"))
        if comm is not None:
            commissions.append(comm)
        ts = row.get("dateTime")
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                ts = None
        elif isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        if ts is not None:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if earliest is None or ts < earliest:
                earliest = ts
        ex_id = _safe_str(row.get("ibExecID"))
        if ex_id:
            leg_exec_ids.append(ex_id)
        oref = _safe_str(row.get("orderReference"))
        order_refs.append(oref or "")
        cur = _safe_str(row.get("currency"))
        if cur:
            currencies.add(cur)
        exch = _safe_str(row.get("exchange"))
        if exch:
            exchanges.add(exch)

    if earliest is None:
        return None

    # gcd over absolute integer quantities; falls back to 1 if any non-integer
    abs_int_qtys = []
    for q in quantities:
        a = abs(q)
        if a == 0:
            continue
        if float(int(a)) == a:
            abs_int_qtys.append(int(a))
        else:
            abs_int_qtys = []
            break
    combo_qty = reduce(gcd, abs_int_qtys) if abs_int_qtys else 1
    if combo_qty <= 0:
        combo_qty = 1

    combo_price = signed_cash / combo_qty if combo_qty else 0.0
    combo_side = "BUY" if signed_cash > 0 else "SELL"
    combo_commission = sum(commissions) if commissions else None

    # order_ref: only carry over if every leg has the same non-empty value
    if order_refs and all(o for o in order_refs) and len(set(order_refs)) == 1:
        combo_order_ref = order_refs[0]
    else:
        combo_order_ref = None

    # Derive the combo summary's ib_exec_id from the leg numbering. IBKR formats
    # ibExecID as `<acct-prefix>.<order-prefix>.<leg-number>.<revision>` and reserves
    # leg "01" for the BAG/combo summary slot (legs themselves are .02, .03, ...).
    # Use that natural slot when all legs share the same prefix; otherwise fall back
    # to a brokerageOrderID-based ID so we always have a deterministic key.
    combo_exec_id: str | None = None
    if leg_exec_ids:
        prefixes = set()
        for ex_id in leg_exec_ids:
            parts = ex_id.split(".")
            if len(parts) >= 4:
                prefixes.add(".".join(parts[:2]))
        if len(prefixes) == 1:
            combo_exec_id = f"{next(iter(prefixes))}.01.01"
    if combo_exec_id is None:
        combo_exec_id = f"{brokerage_order_id}.combo"
    combo_exec_id_base, _ = _parse_exec_id(combo_exec_id)

    raw = {
        "synthetic": True,
        "brokerage_order_id": brokerage_order_id,
        "leg_ib_exec_ids": leg_exec_ids,
        "leg_count": len(leg_rows),
        "signed_net_cash": signed_cash,
        "leg_quantities": quantities,
        # TWS-compatible contract sub-dict so display helpers render the BAG row
        # like a TWS combo (e.g. "AAPL Combo" via contract_display_name's BAG rule).
        "contract": {
            "conId": None,
            "symbol": parent_symbol,
            "secType": "BAG",
            "exchange": next(iter(exchanges)) if len(exchanges) == 1 else None,
            "currency": next(iter(currencies)) if len(currencies) == 1 else None,
            "localSymbol": None,
            "lastTradeDateOrContractMonth": None,
            "strike": None,
            "right": None,
            "tradingClass": None,
            "multiplier": None,
        },
    }

    stmt = (
        insert(TradeExecution)
        .values(
            trade_id=parent_trade_id,
            account_id=account_id,
            ib_exec_id=combo_exec_id,
            exec_id_base=combo_exec_id_base,
            exec_revision=1,
            ib_perm_id=None,
            ib_order_id=None,
            order_ref=combo_order_ref,
            sec_type="BAG",
            con_id=None,
            exec_role="combo_summary",
            executed_at=earliest,
            quantity=float(combo_qty),
            price=combo_price,
            side=combo_side,
            exchange=next(iter(exchanges)) if len(exchanges) == 1 else None,
            currency=next(iter(currencies)) if len(currencies) == 1 else None,
            liquidity=None,
            commission=combo_commission,
            is_canonical=True,
            data_source="flex",
            flex_transaction_id=None,
            raw=raw,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["ib_exec_id"],
            set_={
                "trade_id": parent_trade_id,
                "quantity": float(combo_qty),
                "price": combo_price,
                "side": combo_side,
                "commission": combo_commission,
                "exec_role": "combo_summary",
                "sec_type": "BAG",
                "executed_at": earliest,
                "order_ref": combo_order_ref,
                "raw": raw,
                "fetched_at": now,
                "updated_at": now,
            },
        )
    )
    result = session.execute(stmt)
    inserted = getattr(result, "rowcount", None) == 1
    return {
        "inserted": inserted,
        "exec_id_base": combo_exec_id_base,
        "ib_exec_id": combo_exec_id,
        "qty": combo_qty,
        "price": combo_price,
    }


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
