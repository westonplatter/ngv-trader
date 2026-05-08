"""Fetch the IBKR FlexQuery daily report, save it, and grep for BAG/combo markers.

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
from datetime import date, timedelta
from pathlib import Path

from loguru import logger
from ngv_reports_ibkr.flex_client import DateRange, FlexClient


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


def grep_summary(xml_text: str) -> None:
    """Print line counts for combo-relevant tokens — same idea as `grep -ic`."""
    needles = ["BAG", "Combo", "combo", "Spread", "spread", "ComboTrade", "MultiLeg"]
    print("\n=== grep summary ===")
    for n in needles:
        count = xml_text.count(n)
        print(f"  {n:<12} {count}")

    print("\n=== sample lines for each non-zero hit (first 3) ===")
    lines = xml_text.splitlines()
    for n in needles:
        matches = [(i + 1, ln) for i, ln in enumerate(lines) if n in ln]
        if not matches:
            continue
        print(f"\n  --- {n} ({len(matches)} line(s)) ---")
        for line_no, ln in matches[:3]:
            snippet = ln if len(ln) <= 240 else ln[:240] + "…"
            print(f"  L{line_no}: {snippet}")

    print("\n=== distinct attribute values that could mark a combo ===")
    for attr in ("levelOfDetail", "assetCategory", "secType", "transactionType"):
        values = sorted(set(re.findall(rf'{attr}="([^"]*)"', xml_text)))
        print(f"  {attr}: {values}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch FlexQuery daily report and grep for BAG/combo markers")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--name", type=str, default=None, help="IB_JSON entry name (default: first entry)")
    args = parser.parse_args()

    entry = _ib_json_entry(args.name)
    flex_token = entry.get("flex_token")
    query_id = entry.get("daily")
    if not (flex_token and query_id):
        logger.error("IB_JSON entry name={!r} missing flex_token or daily query_id", entry.get("name"))
        return 1

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=args.days)
    logger.info(f"Fetching daily report: {start_date} → {end_date}")

    xml_text = FlexClient().fetch_flex_report(
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

    grep_summary(xml_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
