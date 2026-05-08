"""Backfill historical trade executions from IBKR FlexQuery.

For each token in IB_JSON, fetches one chunked report and dispatches per account
returned by the report (a single token sees all linked accounts). Writes one
flex_sync_log row per (account, chunk).

Usage:
    uv run python scripts/backfill_flex_trades.py [--days 180] [--account U1234567]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import date, timedelta

from src.db import get_engine
from src.services.flex_trade_sync import (
    FlexTokenExpiredError,
    fetch_flex_report,
    previous_business_day,
    recompute_aggregates_for_trades,
    sync_flex_trades,
)

logger = logging.getLogger("backfill_flex_trades")

MAX_FLEX_RANGE_DAYS = 365


def _chunked_ranges(start: date, end: date, max_days: int = MAX_FLEX_RANGE_DAYS) -> list[tuple[date, date]]:
    """Split [start, end] into ≤max_days windows."""
    chunks: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=max_days - 1), end)
        chunks.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return chunks


def _tokens_from_ib_json() -> list[dict]:
    raw = os.environ.get("IB_JSON")
    if not raw:
        raise RuntimeError("IB_JSON environment variable is not set")
    return json.loads(raw).get("accounts", [])


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill FlexQuery trade history")
    parser.add_argument("--days", type=int, default=180, help="Lookback window in calendar days (default: 180)")
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Restrict to a single IBKR account ID (e.g. U1234567)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

    end_date = previous_business_day()
    start_date = end_date - timedelta(days=args.days)

    engine = get_engine()
    tokens = _tokens_from_ib_json()

    overall_touched: set[int] = set()
    overall_status: dict[str, str] = {}

    for entry in tokens:
        token_alias = entry.get("name") or "<unnamed>"
        flex_token = entry.get("flex_token")
        query_id = entry.get("daily")
        if not (flex_token and query_id):
            logger.warning("Skipping IB_JSON entry %r: missing flex_token or daily query_id", token_alias)
            continue

        chunks = _chunked_ranges(start_date, end_date)
        logger.info(
            "token=%s start=%s end=%s chunks=%d",
            token_alias,
            start_date.isoformat(),
            end_date.isoformat(),
            len(chunks),
        )

        for chunk_start, chunk_end in chunks:
            try:
                report = fetch_flex_report(flex_token, query_id, chunk_start, chunk_end)
            except FlexTokenExpiredError:
                logger.error("token=%s: flex token expired/invalid; aborting", token_alias)
                overall_status[token_alias] = "error: token"
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception("token=%s chunk=%s..%s: fetch failed: %s", token_alias, chunk_start, chunk_end, exc)
                overall_status[token_alias] = f"error: {type(exc).__name__}"
                continue

            account_ids = report.account_ids()
            logger.info(
                "  token=%s chunk=%s..%s discovered accounts: %s",
                token_alias,
                chunk_start,
                chunk_end,
                account_ids,
            )

            for account_id in account_ids:
                if args.account and account_id != args.account:
                    continue
                try:
                    result = sync_flex_trades(
                        engine=engine,
                        account_code=account_id,
                        report=report,
                        start_date=chunk_start,
                        end_date=chunk_end,
                        skip_aggregate_recompute=True,
                    )
                    overall_touched.update(result.get("touched_trade_ids", []))
                    key = f"{token_alias}:{account_id}"
                    if overall_status.get(key) != "error":
                        overall_status[key] = "success"
                except Exception as exc:  # noqa: BLE001
                    logger.exception("account=%s: per-account sync failed: %s", account_id, exc)
                    overall_status[f"{token_alias}:{account_id}"] = f"error: {type(exc).__name__}"

    if overall_touched:
        logger.info("Recomputing aggregates for %d touched trades", len(overall_touched))
        recompute_aggregates_for_trades(engine, overall_touched)

    logger.info("Backfill complete: %s", overall_status)
    return 0 if all(v == "success" for v in overall_status.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
