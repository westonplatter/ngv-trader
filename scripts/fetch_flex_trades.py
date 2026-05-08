"""Fetch trades from IBKR Flex Query for the last 14 days and save to file."""

import json
import os
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger
from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import DateRange, FlexClient

ib_json = json.loads(os.environ["IB_JSON"])
flex_token = ib_json["accounts"][0]["flex_token"]
query_id = ib_json["accounts"][0]["daily"]

end_date = date.today() - timedelta(days=1)
start_date = end_date - timedelta(days=14)

date_range = DateRange(from_date=start_date, to_date=end_date)
logger.info(f"Date range: {date_range.from_date} to {date_range.to_date}")
logger.info(f"Query params: {date_range.to_query_params()}")

client = FlexClient()

try:
    xml_data = client.fetch_flex_report(token=flex_token, query_id=query_id, date_range=date_range)
    logger.debug(f"Report fetched with custom date range")
    logger.debug(f"XML data length: {len(xml_data)} bytes")
except Exception as e:
    logger.error(f"Error fetching report: {e}")
    raise

report = CustomFlexReport()
report.root = ET.fromstring(xml_data)

output_dir = Path(__file__).parent / "data"
output_dir.mkdir(exist_ok=True)

all_trades: list[pd.DataFrame] = []

for account_id in report.account_ids():
    df = report.trades_by_account_id(account_id)
    if df is None:
        logger.info(f"Account {account_id}: no trades")
        continue
    logger.info(f"Account {account_id}: {len(df)} trades")
    all_trades.append(df)

if all_trades:
    combined = pd.concat(all_trades, ignore_index=True)
    output_path = output_dir / "trades.csv"
    combined.to_csv(output_path, index=False)
    logger.info(f"Saved {len(combined)} trades to {output_path}")
    logger.info(f"Columns: {list(combined.columns)}")
else:
    logger.info("No trades found for any account")
