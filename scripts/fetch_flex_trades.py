"""Fetch the IBKR FlexQuery daily report, save it, and print a summary.

Usage:
    op run --env-file=.env.prod -- uv run python scripts/fetch_flex_trades.py [--days 14] [--name <ib_json_name>]

Notes:
- Hardcoded to the `daily` query_id from IB_JSON. `weekly`/`annual` are unused.
- scripts/data/ is gitignored (contains real account/exec data).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from loguru import logger
from ngv_reports_ibkr.flex_client import DateRange

from src.services.flex_client_factory import make_flex_client
from src.utils.ibkr_account import mask_ibkr_account


def _ib_json_entry(name: str | None) -> dict:
    raw = os.environ.get("IB_JSON")
    if not raw:
        raise RuntimeError("IB_JSON environment variable is not set")
    accounts = json.loads(raw).get("accounts", [])
    if not accounts:
        raise RuntimeError("IB_JSON has no accounts configured")
    if name:
        match = next((a for a in accounts if a.get("name") == name), None)
        if match is None:
            raise RuntimeError(f"IB_JSON has no entry for name={name!r}")
        return match
    return accounts[0]


def print_summary(xml_text: str, start_date: date, end_date: date) -> None:
    trade_tags = re.findall(r"<Trade\s[^>]*", xml_text)
    counts: Counter[str] = Counter()
    for tag in trade_tags:
        if 'levelOfDetail="EXECUTION"' not in tag:
            continue
        m = re.search(r'accountId="([^"]*)"', tag)
        if m:
            counts[m.group(1)] += 1

    logger.info("=== date range ===")
    logger.info(f"  start: {start_date}")
    logger.info(f"  end:   {end_date}")

    logger.info("=== trades by account (levelOfDetail=EXECUTION) ===")
    masked = {mask_ibkr_account(a): c for a, c in counts.items()}
    width = max((len(a) for a in masked), default=10)
    for account, count in sorted(masked.items()):
        logger.info(f"  {account:<{width}}  {count}")
    logger.info(f"  {'TOTAL':<{width}}  {sum(masked.values())}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch FlexQuery daily report and print a trade-count summary")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--name", type=str, default=None, help="IB_JSON entry name (default: first entry)")
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD or 'today'). Default: yesterday.",
    )
    args = parser.parse_args()

    entry = _ib_json_entry(args.name)
    flex_token = entry.get("flex_token")
    query_id = entry.get("daily")
    if not (flex_token and query_id):
        logger.error("IB_JSON entry name={!r} missing flex_token or daily query_id", entry.get("name"))
        return 1

    if args.end_date is None:
        end_date = date.today() - timedelta(days=1)
    elif args.end_date.lower() == "today":
        end_date = date.today()
    else:
        end_date = date.fromisoformat(args.end_date)
    start_date = end_date - timedelta(days=args.days)
    logger.info(f"Fetching daily report: {start_date} → {end_date}")

    xml_text = make_flex_client().fetch_flex_report(
        token=flex_token,
        query_id=query_id,
        date_range=DateRange(from_date=start_date, to_date=end_date),
    )
    logger.info(f"XML length: {len(xml_text):,} bytes")

    output_dir = Path(__file__).parent / "data"
    output_dir.mkdir(exist_ok=True)
    xml_path = output_dir / "flex_report_ranged.xml"
    xml_path.write_text(xml_text, encoding="utf-8")
    logger.info(f"Wrote raw XML to {xml_path}")

    print_summary(xml_text, start_date, end_date)
    return 0


if __name__ == "__main__":
    sys.exit(main())
