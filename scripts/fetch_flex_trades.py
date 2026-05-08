"""Fetch trades from IBKR Flex Query and print a summary."""

import json
import os
import xml.etree.ElementTree as ET

from ngv_reports_ibkr.custom_flex_report import CustomFlexReport
from ngv_reports_ibkr.flex_client import FlexClient

ib_json = json.loads(os.environ["IB_JSON"])
flex_token = ib_json["accounts"][0]["flex_token"]
query_id = ib_json["accounts"][0]["daily"]

client = FlexClient()
xml_data = client.fetch_flex_report(token=flex_token, query_id=query_id)

report = CustomFlexReport()
report.root = ET.fromstring(xml_data)

for account_id in report.account_ids():
    df = report.trades_by_account_id(account_id)
    if df is None:
        print(f"Account {account_id}: no trades")
        continue
    print(f"Account {account_id}: {len(df)} trades")
    print(df.head())
