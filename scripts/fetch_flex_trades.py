"""Fetch an IBKR FlexQuery report, save it, and print a summary.

Usage:
    uv run python scripts/fetch_flex_trades.py [--days 14] [--name <token-name>]

Notes:
- Credentials come from the `flexquery_tokens` table, not the environment.
  Seed them with scripts/manage_flex_tokens.py; the token is decrypted with
  FLEX_TOKEN_ENCRYPTION_KEY.
- Without --name, the first active token is used.
- scripts/data/ is gitignored (contains real account/exec data).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from loguru import logger
from ngv_reports_ibkr.flex_client import DateRange

from src.db import get_engine
from src.services.flex_client_factory import make_flex_client
from src.services.flex_credentials import load_credential, mark_used
from src.utils.ibkr_account import mask_ibkr_account


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
    parser.add_argument("--name", type=str, default=None, help="flexquery_tokens.name (default: first active token)")
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD or 'today'). Default: yesterday.",
    )
    args = parser.parse_args()

    engine = get_engine()
    credential = load_credential(engine, args.name)

    if args.end_date is None:
        end_date = date.today() - timedelta(days=1)
    elif args.end_date.lower() == "today":
        end_date = date.today()
    else:
        end_date = date.fromisoformat(args.end_date)
    start_date = end_date - timedelta(days=args.days)
    logger.info(f"Fetching report for token {credential.name!r}: {start_date} → {end_date}")

    xml_text = make_flex_client(span_days=args.days).fetch_flex_report(
        token=credential.token,
        query_id=credential.report_id,
        date_range=DateRange(from_date=start_date, to_date=end_date),
    )
    mark_used(engine, credential.token_id)
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
