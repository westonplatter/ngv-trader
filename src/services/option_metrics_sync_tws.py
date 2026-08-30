"""Option-metrics TWS sync: live greeks/IV for held option positions.

Deliberately a **separate** job from the real-time mark fetch
(``intraday.sync.tws`` → ``latest_quote``). This job fetches ``modelGreeks`` for
the held OPT/FOP contracts and writes only ``latest_option_metrics``, so the two
jobs never clobber each other's columns and can run on independent cadences.

Source of held instruments is ``ib.positions()`` (self-contained — no dependency
on the mark job having run first), filtered to option sec types. Greeks are read
off the same ticker shape the research path uses in ``market_data.py``.

Writes are **preserving**: a con_id whose fetch carried no greeks keeps whatever
is already stored (see ``_write_option_metrics``), so rerunning the job can never
leave you with less than you had.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from ib_async import IB
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import LatestOptionMetrics
from src.services.intraday_sync_tws import (
    _ensure_market_data_exchange,
    _fetch_tickers,
    _safe_float,
)

logger = logging.getLogger(__name__)

# Option sec types carrying greeks (equity + futures options).
OPTION_SEC_TYPES = {"OPT", "FOP"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _extract_greeks(ticker: Any) -> dict[str, float | None]:
    """Pull IV + greeks + underlying price off a ticker's ``modelGreeks``.

    Same shape as ``market_data.py`` uses for the research tables. Every field is
    run through ``_safe_float`` so NaN/inf/sentinel values never land in the row.
    """
    greeks = getattr(ticker, "modelGreeks", None)
    if greeks is None:
        return {"iv": None, "delta": None, "gamma": None, "theta": None, "vega": None, "und_price": None}
    return {
        "iv": _safe_float(getattr(greeks, "impliedVol", None)),
        "delta": _safe_float(getattr(greeks, "delta", None)),
        "gamma": _safe_float(getattr(greeks, "gamma", None)),
        "theta": _safe_float(getattr(greeks, "theta", None)),
        "vega": _safe_float(getattr(greeks, "vega", None)),
        "und_price": _safe_float(getattr(greeks, "undPrice", None)),
    }


def _write_option_metrics(session: Session, tickers_by_con_id: dict[int, Any], now: datetime) -> tuple[int, int]:
    """Upsert ``latest_option_metrics`` for held options, preserving prior greeks.

    A fetch that returns no ``modelGreeks`` writes **nothing** for that con_id:
    the stored row keeps its last good values and its original timestamps. This
    matters because ``reqTickers`` is a snapshot and the model-greeks tick often
    arrives after the snapshot ends, so coverage varies run to run — an
    unconditional upsert let an empty run erase greeks captured earlier in the
    day. A partial fetch writes only the fields that actually arrived, for the
    same reason.

    ``market_ts``/``ingested_at`` therefore advance only when greeks were
    received, so a stored row's timestamp reflects the freshness of its values
    rather than the time of the last attempt.

    Returns ``(written, skipped)`` so the caller can log coverage.
    """
    written = 0
    skipped = 0
    for con_id, ticker in tickers_by_con_id.items():
        greeks = {k: v for k, v in _extract_greeks(ticker).items() if v is not None}
        if not greeks:
            logger.warning(
                "No modelGreeks for held option con_id=%d; leaving stored metrics untouched",
                con_id,
            )
            skipped += 1
            continue
        vals = {"con_id": con_id, "market_ts": now, "ingested_at": now, **greeks}
        session.execute(
            insert(LatestOptionMetrics)
            .values(**vals)
            .on_conflict_do_update(
                index_elements=["con_id"],
                set_={k: v for k, v in vals.items() if k != "con_id"},
            )
        )
        written += 1
    return written, skipped


def run_option_metrics_sync(engine: Engine, ib: IB) -> dict:
    """Fetch greeks/IV for held options and write ``latest_option_metrics``.

    The IB session is provided by the caller (worker pool), matching
    ``run_intraday_sync``. Returns counts
    ``{options, quotes, with_greeks, skipped_no_greeks}`` — ``quotes`` is tickers
    received, ``with_greeks`` is rows actually written, and ``skipped_no_greeks``
    counts held options whose stored metrics were left untouched because the
    fetch carried no greeks.
    """
    now = _now_utc()

    positions = ib.positions()
    option_contracts = [p.contract for p in positions if getattr(p.contract, "conId", None) and getattr(p.contract, "secType", None) in OPTION_SEC_TYPES]
    logger.info("Option-metrics sync: %d held option contracts", len(option_contracts))
    if not option_contracts:
        return {"options": 0, "quotes": 0, "with_greeks": 0, "skipped_no_greeks": 0}

    # ib.positions() contracts carry a conId but no exchange, which reqTickers
    # rejects; qualify them first (same as the mark job).
    option_contracts = _ensure_market_data_exchange(ib, option_contracts)
    tickers_by_con_id = _fetch_tickers(ib, option_contracts)

    with Session(engine) as session:
        written, skipped = _write_option_metrics(session, tickers_by_con_id, now)
        session.commit()

    counts = {
        "options": len(option_contracts),
        "quotes": len(tickers_by_con_id),
        "with_greeks": written,
        "skipped_no_greeks": skipped,
    }
    logger.info("Option-metrics sync complete: %s", counts)
    return counts
