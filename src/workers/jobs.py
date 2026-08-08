"""Job handler functions and dispatcher for the background worker.

This module owns the `handle_*` functions, the `IBSessionPool` used to share
TWS connections across handlers, the `get_handler` dispatch table, and the
small private helpers that exist only to support the handlers. The CLI
entrypoint in `scripts/work_jobs.py` imports `get_handler` and `IBSessionPool`
from here and drives the polling loop.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ib_async import IB
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from src.models import Job
from src.services.flex_credentials import (
    RATE_LIMIT_ERROR_CODE,
    RATE_LIMIT_PAUSE_SECONDS,
    SEED_HINT,
    FlexCredential,
    is_rate_limit_error,
    load_active_credentials,
    load_credential_by_id,
    mark_used,
    pause_token,
)
from src.services.jobs import (
    JOB_TYPE_CONTRACTS_CHAIN_SYNC,
    JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT,
    JOB_TYPE_CONTRACTS_SYNC,
    JOB_TYPE_CONTRACTS_SYNC_ACTIVATED,
    JOB_TYPE_INTRADAY_SYNC_TWS,
    JOB_TYPE_MARKET_DATA_FUTURES_OPTIONS,
    JOB_TYPE_MARKET_DATA_FUTURES_PRICES,
    JOB_TYPE_MARKET_DATA_SNAPSHOT,
    JOB_TYPE_OPTION_METRICS_SYNC_TWS,
    JOB_TYPE_ORDER_FETCH_SYNC,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
    JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
    JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST,
    JOB_TYPE_TRADES_SYNC_FLEXQUERY,
    JOB_TYPE_WATCHLIST_ADD_INSTRUMENT,
    JOB_TYPE_WATCHLIST_QUOTES_REFRESH,
    JobDeferred,
)
from src.utils.env_vars import get_int_env


@dataclass
class IBPoolEntry:
    ib: IB
    last_used_monotonic: float


class IBSessionPool:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, int, int], IBPoolEntry] = {}

    def get(self, *, host: str, port: int, client_id: int, connect_timeout_seconds: float) -> IB:
        key = (host, port, client_id)
        entry = self._entries.get(key)
        now = time.monotonic()
        if entry is not None and entry.ib.isConnected():
            entry.last_used_monotonic = now
            return entry.ib

        if entry is not None:
            if entry.ib.isConnected():
                entry.ib.disconnect()
            del self._entries[key]

        ib = IB()
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out connecting to TWS/Gateway " f"(host={host}, port={port}, client_id={client_id}, timeout={connect_timeout_seconds}s)."
            ) from exc
        self._entries[key] = IBPoolEntry(ib=ib, last_used_monotonic=now)
        return ib

    def close_idle(self, *, max_idle_seconds: float) -> int:
        if max_idle_seconds <= 0:
            return 0
        now = time.monotonic()
        removed = 0
        for key, entry in list(self._entries.items()):
            is_stale = (now - entry.last_used_monotonic) >= max_idle_seconds
            if is_stale or not entry.ib.isConnected():
                if entry.ib.isConnected():
                    entry.ib.disconnect()
                del self._entries[key]
                removed += 1
        return removed

    def close_all(self) -> None:
        for key, entry in list(self._entries.items()):
            if entry.ib.isConnected():
                entry.ib.disconnect()
            del self._entries[key]

    def active_count(self) -> int:
        return sum(1 for entry in self._entries.values() if entry.ib.isConnected())


def resolve_tws_connection(
    payload: dict,
    *,
    default_client_id: int,
    connect_timeout_default_seconds: float = 20.0,
) -> tuple[str, int, int, float]:
    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")
    connect_timeout_raw = payload.get("connect_timeout_seconds")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = default_client_id

    if isinstance(connect_timeout_raw, (int, float)):
        connect_timeout_seconds = float(connect_timeout_raw)
    else:
        connect_timeout_seconds = connect_timeout_default_seconds

    return host, port, client_id, connect_timeout_seconds


def handle_positions_sync_tws(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.position_sync_tws import sync_positions_with_ib

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=31)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    fetched_positions_count = sync_positions_with_ib(engine=engine, ib=ib)
    return {
        "fetched_positions_count": fetched_positions_count,
        "host": host,
        "port": port,
        "client_id": client_id,
        "connect_timeout_seconds": connect_timeout_seconds,
    }


def handle_contracts_sync(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from ib_async import Contract, Future

    from src.services.contract_sync import sync_contracts_with_ib

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=32)

    # Build contract specs from payload, default to CL futures
    raw_specs = payload.get("specs")
    specs: list[Contract]
    if isinstance(raw_specs, list) and raw_specs:
        specs = []
        for raw in raw_specs:
            if not isinstance(raw, dict):
                continue
            sec_type = raw.get("sec_type", "FUT").upper()
            symbol = raw.get("symbol", "CL")
            exchange = raw.get("exchange", "")
            currency = raw.get("currency", "USD")

            if not exchange:
                raise RuntimeError(f"No exchange specified for {symbol} {sec_type}. " "The job payload must include an exchange.")

            if sec_type == "FUT":
                specs.append(Future(symbol=symbol, exchange=exchange, currency=currency))
            elif sec_type in ("STK", "OPT"):
                specs.append(
                    Contract(
                        symbol=symbol,
                        secType=sec_type,
                        exchange="SMART",
                        currency=currency,
                    )
                )
            else:
                specs.append(
                    Contract(
                        symbol=symbol,
                        secType=sec_type,
                        exchange=exchange,
                        currency=currency,
                    )
                )
        if not specs:
            specs = [Future("CL", exchange="NYMEX", currency="USD")]
    else:
        specs = [Future("CL", exchange="NYMEX", currency="USD")]

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return sync_contracts_with_ib(
        engine=engine,
        ib=ib,
        specs=specs,
    )


def handle_watchlist_add_instrument(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.watchlist_instrument_sync import fetch_and_add_instrument_with_ib

    payload = job.payload or {}

    watch_list_id = payload.get("watch_list_id")
    if not isinstance(watch_list_id, int):
        raise ValueError("watchlist.add_instrument job requires integer 'watch_list_id' in payload.")

    symbol = payload.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("watchlist.add_instrument job requires string 'symbol' in payload.")

    sec_type = payload.get("sec_type")
    if not isinstance(sec_type, str) or not sec_type.strip():
        raise ValueError("watchlist.add_instrument job requires string 'sec_type' in payload.")

    exchange = payload.get("exchange")
    if not isinstance(exchange, str) or not exchange.strip():
        raise ValueError("watchlist.add_instrument job requires string 'exchange' in payload.")

    contract_month = payload.get("contract_month")
    if contract_month is not None and not isinstance(contract_month, str):
        raise ValueError("'contract_month' must be a string if provided.")

    strike_raw = payload.get("strike")
    strike = float(strike_raw) if strike_raw is not None else None

    right = payload.get("right")
    if right is not None and not isinstance(right, str):
        raise ValueError("'right' must be a string if provided.")

    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=34)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return fetch_and_add_instrument_with_ib(
        engine=engine,
        ib=ib,
        watch_list_id=watch_list_id,
        symbol=symbol.strip().upper(),
        sec_type=sec_type.strip().upper(),
        exchange=exchange.strip().upper(),
        contract_month=contract_month,
        strike=strike,
        right=right,
    )


def handle_watchlist_quotes_refresh(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.watchlist_quotes import refresh_watch_list_quotes_with_ib

    payload = job.payload or {}
    watch_list_id = payload.get("watch_list_id")
    if not isinstance(watch_list_id, int):
        raise ValueError("watchlist.quotes_refresh job requires integer 'watch_list_id' in payload.")

    host = str(payload.get("host") or "127.0.0.1")
    port_raw = payload.get("port")
    client_id_raw = payload.get("client_id")
    connect_timeout_raw = payload.get("connect_timeout_seconds")

    if isinstance(port_raw, int):
        port = port_raw
    else:
        port = get_int_env("BROKER_TWS_PORT")
    if port is None:
        raise RuntimeError("BROKER_TWS_PORT is not set and no port was provided in job payload.")

    if isinstance(client_id_raw, int):
        client_id = client_id_raw
    else:
        client_id = get_int_env("BROKER_TWS_QUOTES_CLIENT_ID", 141)
    if client_id is None:
        raise RuntimeError("BROKER_TWS_QUOTES_CLIENT_ID is not set and no client_id was provided in job payload.")

    if isinstance(connect_timeout_raw, (int, float)):
        connect_timeout_seconds = float(connect_timeout_raw)
    else:
        connect_timeout_seconds = 10.0

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return refresh_watch_list_quotes_with_ib(
        engine=engine,
        watch_list_id=watch_list_id,
        ib=ib,
    )


def handle_order_fetch_sync(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.order_sync_tws import sync_orders_with_ib

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=0)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    result = sync_orders_with_ib(
        engine=engine,
        ib=ib,
        client_id=client_id,
    )
    return {
        **result,
        "host": host,
        "port": port,
        "client_id": client_id,
        "connect_timeout_seconds": connect_timeout_seconds,
    }


def handle_trades_sync_tws(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.trade_sync_tws import sync_trades_with_ib

    payload = job.payload or {}
    lookback_days_raw = payload.get("lookback_days")
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=33)

    if isinstance(lookback_days_raw, int):
        lookback_days = lookback_days_raw
    else:
        lookback_days = 7

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    result = sync_trades_with_ib(
        engine=engine,
        ib=ib,
        lookback_days=lookback_days,
    )
    return {
        **result,
        "host": host,
        "port": port,
        "client_id": client_id,
        "connect_timeout_seconds": connect_timeout_seconds,
        "lookback_days": lookback_days,
    }


def _run_flexquery_sync(
    engine: Engine,
    start_date: date,
    end_date: date,
    filter_account: str | None,
    sync_account: Callable[[str, Any, FlexCredential], dict],
    filter_token_id: int | None = None,
) -> dict:
    """Fetch every active token's report and sync the accounts each one covers.

    One token can return several accounts, and several tokens can be configured,
    so this runs the whole active set rather than the first entry. A token whose
    fetch fails is recorded and skipped; the run only fails outright when no
    token produced a report. Token values never reach the returned dict — the
    result is persisted to ``jobs.result``, which is plaintext.

    ``filter_token_id`` narrows the run to one ``flexquery_tokens.id``. Use it for
    backfills so a token that is erroring or rate-limited is not dragged through
    every job in the series. It keys on the primary key rather than the name so a
    queued job still points at the same token after a rename.
    """
    from src.services.trade_sync_flexquery import fetch_flex_report

    credentials = load_active_credentials(engine)
    if filter_token_id is not None:
        credentials = [c for c in credentials if c.token_id == filter_token_id]
        if not credentials:
            raise RuntimeError(f"No active FlexQuery token with id {filter_token_id}.")

    per_account: dict[str, dict] = {}
    tokens_synced: list[str] = []
    token_errors: dict[str, str] = {}
    duplicate_accounts: list[str] = []

    for credential in credentials:
        try:
            report = fetch_flex_report(credential.token, credential.report_id, start_date, end_date)
        except Exception as exc:  # noqa: BLE001 — one bad token must not stop the rest
            token_errors[credential.name] = credential.redact(f"{type(exc).__name__}: {exc}")
            continue

        mark_used(engine, credential.token_id)
        tokens_synced.append(credential.name)

        for account_id in report.account_ids():
            if filter_account and account_id != filter_account:
                continue
            if account_id in per_account:
                # Two tokens cover the same account. Last writer wins, matching
                # the account-stamping rule, but the overlap is worth surfacing.
                duplicate_accounts.append(account_id)
            per_account[account_id] = sync_account(account_id, report, credential)

    if not tokens_synced:
        detail = "; ".join(f"{name}: {message}" for name, message in token_errors.items())
        raise RuntimeError(f"No FlexQuery token returned a report. {detail}")

    return {
        "per_account": per_account,
        "accounts_synced": list(per_account),
        "tokens_synced": tokens_synced,
        "token_errors": token_errors,
        "duplicate_accounts": sorted(set(duplicate_accounts)),
    }


def _flexquery_window(payload: dict) -> tuple[date, date]:
    """Resolve the requested window, defaulting to the trailing `days` span."""
    from datetime import timedelta as _td

    from src.services.trade_sync_flexquery import previous_business_day

    if "start_date" in payload and "end_date" in payload:
        return (
            date.fromisoformat(payload["start_date"]),
            date.fromisoformat(payload["end_date"]),
        )
    days = int(payload.get("days", 7))
    end_date = previous_business_day()
    return end_date - _td(days=days), end_date


def handle_trades_sync_flexquery(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Entrypoint: fan out to one `initiate_request` job per active token.

    Kept so existing callers, schedules, and already-queued jobs keep working
    after the split. It no longer fetches anything itself — asking IBKR for a
    statement and collecting it are separate jobs now, so a worker slot is never
    held open sleeping through statement generation.
    """
    from src.services.jobs import (
        JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST,
        enqueue_job,
    )

    payload = job.payload or {}
    filter_account = payload.get("account_code")
    filter_token_id = payload.get("token_id")
    start_date, end_date = _flexquery_window(payload)

    credentials = load_active_credentials(engine)
    if filter_token_id is not None:
        credentials = [c for c in credentials if c.token_id == filter_token_id]
        if not credentials:
            raise RuntimeError(f"No active FlexQuery token with id {filter_token_id}.")

    enqueued: list[dict] = []
    with Session(engine) as session:
        for credential in credentials:
            child_payload: dict[str, Any] = {
                "token_id": credential.token_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if filter_account:
                child_payload["account_code"] = filter_account
            child = enqueue_job(
                session=session,
                job_type=JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST,
                payload=child_payload,
                source=f"job:{job.id}",
                request_text=None,
            )
            enqueued.append({"job_id": child.id, "token": credential.name})
        session.commit()

    if not enqueued:
        raise RuntimeError(f"No active FlexQuery tokens are configured. {SEED_HINT}")

    return {
        "phase": "fan_out",
        "window": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        "initiated": enqueued,
    }


def handle_trades_flexquery_initiate_request(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Phase 1: ask IBKR to build the statement, then schedule the collection.

    Returns as soon as IBKR hands back a reference code. The wait happens
    between jobs, not inside this one, so repeated `1001` responses can never
    pile up into the `1025: Too many failed attempts` lockout that repeated
    SendRequests cause.
    """
    from ngv_reports_ibkr.flex_client import DateRange, FlexClientError

    from src.services.flex_client_factory import (
        first_check_delay_seconds,
        make_flex_client,
    )
    from src.services.jobs import (
        JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
        enqueue_job,
        now_utc,
    )

    payload = job.payload or {}
    token_id = payload.get("token_id")
    if token_id is None:
        raise RuntimeError("initiate_request requires a token_id in the payload.")
    start_date, end_date = _flexquery_window(payload)
    span_days = (end_date - start_date).days

    credential = load_credential_by_id(engine, int(token_id))
    client = make_flex_client(span_days=span_days, max_retries=1)

    try:
        reference_code = client.send_flex_request(
            token=credential.token,
            query_id=credential.report_id,
            date_range=DateRange(from_date=start_date, to_date=end_date),
        )
    except FlexClientError as exc:
        # A 1025 means IBKR has cooled this token off. Record the pause so the
        # fetch phase holds back and the UI can show why, then wait out the
        # window rather than re-sending on the short cadence.
        if is_rate_limit_error(exc):
            until = pause_token(engine, credential.token_id, f"IBKR rate-limited this token ({RATE_LIMIT_ERROR_CODE}).")
            raise JobDeferred(
                credential.redact(f"token rate-limited; paused until {until.isoformat()}"),
                RATE_LIMIT_PAUSE_SECONDS,
            ) from None
        raise JobDeferred(
            credential.redact(f"send_flex_request not accepted yet: {type(exc).__name__}: {exc}"),
            first_check_delay_seconds(span_days),
        ) from None

    mark_used(engine, credential.token_id)
    check_in = first_check_delay_seconds(span_days)

    collect_payload: dict[str, Any] = {
        "token_id": credential.token_id,
        "reference_code": reference_code,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "checks": 0,
    }
    if payload.get("account_code"):
        collect_payload["account_code"] = payload["account_code"]

    with Session(engine) as session:
        follow_up = enqueue_job(
            session=session,
            job_type=JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT,
            payload=collect_payload,
            source=f"job:{job.id}",
            request_text=None,
        )
        # Hold the collection back until IBKR has plausibly finished building.
        follow_up.available_at = now_utc() + timedelta(seconds=check_in)
        follow_up_id = follow_up.id
        session.commit()

    return {
        "phase": "initiate_request",
        "token": credential.name,
        "reference_code": reference_code,
        "span_days": span_days,
        "fetch_report_job_id": follow_up_id,
        "first_check_in_seconds": check_in,
    }


def handle_trades_flexquery_fetch_report(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Phase 2: collect the statement for a reference code and sync it.

    Defers itself while IBKR is still building. Each deferral costs a bounded
    check rather than a retry attempt, so a slow statement does not exhaust the
    budget that exists for real failures.
    """
    from defusedxml import ElementTree as ET
    from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
    from ngv_reports_ibkr.flex_client import FlexClientError

    from src.services.flex_client_factory import (
        MAX_STATEMENT_CHECKS,
        RECHECK_DELAY_SECONDS,
        make_flex_client,
    )
    from src.services.trade_sync_flexquery import sync_flex_trades

    payload = job.payload or {}
    reference_code = payload.get("reference_code")
    token_id = payload.get("token_id")
    if not reference_code or token_id is None:
        raise RuntimeError("fetch_report requires token_id and reference_code in the payload.")

    filter_account = payload.get("account_code")
    start_date, end_date = _flexquery_window(payload)
    checks = int(payload.get("checks", 0))

    credential = load_credential_by_id(engine, int(token_id))

    # A paused token makes no report fetches at all until its cooldown expires.
    # Deferring here costs nothing: the reference code is already issued, so the
    # only thing waiting buys is not adding load while IBKR is annoyed with us.
    paused_for = credential.pause_remaining_seconds()
    if paused_for > 0:
        raise JobDeferred(
            f"token {credential.name!r} is paused for another {paused_for}s",
            paused_for,
        )

    client = make_flex_client(span_days=(end_date - start_date).days, max_retries=1)

    try:
        xml_data = client.get_flex_statement(token=credential.token, reference_code=reference_code)
    except FlexClientError as exc:
        if is_rate_limit_error(exc):
            until = pause_token(engine, credential.token_id, f"IBKR rate-limited this token ({RATE_LIMIT_ERROR_CODE}).")
            raise JobDeferred(
                credential.redact(f"token rate-limited; paused until {until.isoformat()}"),
                RATE_LIMIT_PAUSE_SECONDS,
            ) from None
        if checks + 1 >= MAX_STATEMENT_CHECKS:
            raise RuntimeError(credential.redact(f"Statement never became ready after {MAX_STATEMENT_CHECKS} checks: {type(exc).__name__}: {exc}")) from None
        # Record the check on the job itself so the count survives the requeue.
        job.payload = {**payload, "checks": checks + 1}
        raise JobDeferred(
            credential.redact(f"statement not ready (check {checks + 1}/{MAX_STATEMENT_CHECKS}): {type(exc).__name__}: {exc}"),
            RECHECK_DELAY_SECONDS,
        ) from None

    report = CustomFlexReport()
    report.root = ET.fromstring(xml_data)

    per_account: dict[str, dict] = {}
    for account_id in report.account_ids():
        if filter_account and account_id != filter_account:
            continue
        per_account[account_id] = sync_flex_trades(
            engine=engine,
            account_code=account_id,
            report=report,
            start_date=start_date,
            end_date=end_date,
            flex_query_token_id=credential.token_id,
        )

    return {
        "phase": "fetch_report",
        "per_account": per_account,
        "accounts_synced": list(per_account),
        "tokens_synced": [credential.name],
        "token_errors": {},
        "duplicate_accounts": [],
        "checks": checks,
    }


def handle_positions_sync_flexquery(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from datetime import date as _date

    from src.services.position_sync_flexquery import sync_flex_positions
    from src.services.trade_sync_flexquery import previous_business_day

    payload = job.payload or {}
    filter_account = payload.get("account_code")
    filter_token_id = payload.get("token_id")

    if "start_date" in payload and "end_date" in payload:
        start_date = _date.fromisoformat(payload["start_date"])
        end_date = _date.fromisoformat(payload["end_date"])
    else:
        end_date = previous_business_day()
        start_date = end_date

    def _sync(account_id: str, report: Any, credential: FlexCredential) -> dict:
        result = sync_flex_positions(
            engine=engine,
            account_code=account_id,
            report=report,
            flex_query_token_id=credential.token_id,
        )
        as_of = result.get("as_of_date")
        return {
            "upserted_count": result.get("upserted_count", 0),
            "as_of_date": as_of.isoformat() if as_of else None,
        }

    return _run_flexquery_sync(engine, start_date, end_date, filter_account, _sync, filter_token_id)


def handle_contracts_chain_sync(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.contract_sync import sync_futures_chain

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=32)

    symbol = payload.get("symbol", "CL")
    exchange = payload.get("exchange")
    if not exchange:
        from src.data.exchanges import resolve_exchange

        exchange = resolve_exchange(symbol, "FUT")
    currency = payload.get("currency", "USD")
    front_n = payload.get("front_n", 6)

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return sync_futures_chain(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        symbol=symbol,
        exchange=exchange,
        currency=currency,
        front_n=front_n,
        connect_timeout_seconds=connect_timeout_seconds,
        ib=ib,
    )


def handle_market_data_futures_prices(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.market_data import fetch_futures_prices

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=35)

    symbol = payload.get("symbol", "CL")
    front_n = payload.get("front_n", 6)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)

    return fetch_futures_prices(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        symbol=symbol,
        front_n=front_n,
        connect_timeout_seconds=connect_timeout_seconds,
        ib=ib,
    )


def handle_market_data_futures_options(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.market_data import fetch_futures_options

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=36)

    symbol = payload.get("symbol", "CL")
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)

    return fetch_futures_options(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        symbol=symbol,
        underlying_con_id=payload.get("underlying_con_id"),
        strike_gte=payload.get("strike_gte"),
        strike_lte=payload.get("strike_lte"),
        dte_lte=payload.get("dte_lte"),
        right=payload.get("right"),
        modulus_eq=payload.get("modulus_eq"),
        front_n=payload.get("front_n", 6),
        connect_timeout_seconds=connect_timeout_seconds,
        ib=ib,
    )


def handle_market_data_snapshot(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.market_data import fetch_snapshot

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=37)

    con_ids = payload.get("con_ids", [])
    if not isinstance(con_ids, list):
        raise ValueError("market_data.snapshot job requires a list of 'con_ids' in payload.")
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)

    return fetch_snapshot(
        engine=engine,
        host=host,
        port=port,
        client_id=client_id,
        con_ids=con_ids,
        connect_timeout_seconds=connect_timeout_seconds,
        ib=ib,
    )


def handle_contracts_qualify_and_snapshot(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Qualify a single option contract and fetch its price in one shot."""
    from ib_async import Contract

    from src.services.contract_sync import sync_contracts_with_ib
    from src.services.market_data import fetch_snapshot

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=38)

    symbol = payload.get("symbol")
    sec_type = payload.get("sec_type", "FOP")
    exchange_val = payload.get("exchange")
    trading_class = payload.get("trading_class", "")
    expiration = payload.get("expiration")
    strike = payload.get("strike")
    right = payload.get("right")

    if not all([symbol, exchange_val, expiration, strike, right]):
        raise ValueError("Missing required fields: symbol, exchange, expiration, strike, right")

    spec = Contract(
        symbol=symbol,
        secType=sec_type,
        exchange=exchange_val,
        currency=payload.get("currency", "USD"),
        lastTradeDateOrContractMonth=expiration,
        tradingClass=trading_class,
        right=right,
        strike=float(strike),
    )

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)

    # Step 1: Qualify and insert into ContractRef
    sync_result = sync_contracts_with_ib(engine=engine, ib=ib, specs=[spec])

    # Step 2: Fetch price if we got a con_id
    snapshot_result = {}
    if sync_result.get("unique_con_ids", 0) > 0:
        # Find the con_id we just qualified
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from src.models import ContractRef

        with Session(engine) as session:
            row = session.execute(
                select(ContractRef.con_id).where(
                    ContractRef.symbol == symbol,
                    ContractRef.sec_type == sec_type,
                    ContractRef.trading_class == trading_class,
                    ContractRef.contract_expiry == expiration,
                    ContractRef.strike == float(strike),
                    ContractRef.right == right,
                    ContractRef.is_active.is_(True),
                )
            ).first()

        if row:
            snapshot_result = fetch_snapshot(
                engine=engine,
                host=host,
                port=port,
                client_id=client_id,
                con_ids=[row.con_id],
                connect_timeout_seconds=connect_timeout_seconds,
                ib=ib,
            )

    return {
        "sync": sync_result,
        "snapshot": snapshot_result,
    }


def handle_contracts_sync_activated(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    from src.services.contract_sync import sync_activated_products_with_ib

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=39)

    symbols_raw = payload.get("symbols")
    symbols = [str(s) for s in symbols_raw] if isinstance(symbols_raw, list) else None

    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return sync_activated_products_with_ib(engine=engine, ib=ib, symbols=symbols)


def handle_intraday_sync_tws(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Run the intraday TWS overlay sync: positions + marks + today's fills."""
    from src.services.intraday_sync_tws import run_intraday_sync

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=40)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return run_intraday_sync(engine=engine, ib=ib)


def handle_option_metrics_sync_tws(job: Job, engine: Engine, ib_pool: IBSessionPool) -> dict:
    """Run the option-metrics TWS sync: live greeks/IV for held options.

    Separate from ``handle_intraday_sync_tws`` (the real-time mark fetch) so the
    two run independently and never clobber each other's columns.
    """
    from src.services.option_metrics_sync_tws import run_option_metrics_sync

    payload = job.payload or {}
    host, port, client_id, connect_timeout_seconds = resolve_tws_connection(payload, default_client_id=41)
    ib = ib_pool.get(host=host, port=port, client_id=client_id, connect_timeout_seconds=connect_timeout_seconds)
    return run_option_metrics_sync(engine=engine, ib=ib)


def get_handler(job_type: str) -> Callable[[Job, Engine, IBSessionPool], dict] | None:
    # TWS sync entries (JOB_TYPE_POSITIONS_SYNC_TWS, JOB_TYPE_TRADES_SYNC_TWS) are
    # intentionally not registered while Flex Query is the active path. The
    # handle_*_tws functions remain defined above so this is reversible by adding
    # the two map entries back when real-time TWS data fetching returns.
    handlers: dict[str, Callable[[Job, Engine, IBSessionPool], dict]] = {
        JOB_TYPE_CONTRACTS_SYNC: handle_contracts_sync,
        JOB_TYPE_CONTRACTS_CHAIN_SYNC: handle_contracts_chain_sync,
        JOB_TYPE_ORDER_FETCH_SYNC: handle_order_fetch_sync,
        JOB_TYPE_WATCHLIST_ADD_INSTRUMENT: handle_watchlist_add_instrument,
        JOB_TYPE_WATCHLIST_QUOTES_REFRESH: handle_watchlist_quotes_refresh,
        JOB_TYPE_TRADES_SYNC_FLEXQUERY: handle_trades_sync_flexquery,
        JOB_TYPE_TRADES_FLEXQUERY_INITIATE_REQUEST: handle_trades_flexquery_initiate_request,
        JOB_TYPE_TRADES_FLEXQUERY_FETCH_REPORT: handle_trades_flexquery_fetch_report,
        JOB_TYPE_POSITIONS_SYNC_FLEXQUERY: handle_positions_sync_flexquery,
        JOB_TYPE_MARKET_DATA_FUTURES_PRICES: handle_market_data_futures_prices,
        JOB_TYPE_MARKET_DATA_FUTURES_OPTIONS: handle_market_data_futures_options,
        JOB_TYPE_MARKET_DATA_SNAPSHOT: handle_market_data_snapshot,
        JOB_TYPE_CONTRACTS_QUALIFY_AND_SNAPSHOT: handle_contracts_qualify_and_snapshot,
        JOB_TYPE_CONTRACTS_SYNC_ACTIVATED: handle_contracts_sync_activated,
        JOB_TYPE_INTRADAY_SYNC_TWS: handle_intraday_sync_tws,
        JOB_TYPE_OPTION_METRICS_SYNC_TWS: handle_option_metrics_sync_tws,
    }
    return handlers.get(job_type)
