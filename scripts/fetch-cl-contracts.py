"""Fetch the NYMEX CL June 2026 65 Call future option from IBKR.

Usage:
  uv run python scripts/fetch-cl-contracts.py --env dev
"""

from __future__ import annotations

import argparse
import logging
import os

from dotenv import load_dotenv
from ib_async import IB

from src.services.ibkr_select_contracts import select_contract_for_watchlist
from src.utils.env_vars import get_int_env

logger = logging.getLogger("scripts:fetch-cl-contracts")


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch CL FOP contract from IBKR.")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    env_file = f".env.{args.env}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    host = "127.0.0.1"
    # Use environment variables if set; fall back to standard local TWS defaults.
    port = get_int_env("BROKER_TWS_PORT", 7496)
    client_id = get_int_env("BROKER_TWS_CLIENT_ID", 50)

    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=30.0)

        contract, match_count = select_contract_for_watchlist(
            ib=ib,
            symbol="CL",
            sec_type="FOP",
            exchange="NYMEX",
            contract_month="2026-06",
            strike=65.0,
            right="C",
        )

        print(f"Matches: {match_count}")
        print(f"  conId:       {contract.conId}")
        print(f"  symbol:      {contract.symbol}")
        print(f"  secType:     {contract.secType}")
        print(f"  exchange:    {contract.exchange}")
        print(f"  localSymbol: {contract.localSymbol}")
        print(f"  expiry:      {contract.lastTradeDateOrContractMonth}")
        print(f"  strike:      {contract.strike}")
        print(f"  right:       {contract.right}")
        print(f"  multiplier:  {contract.multiplier}")
        print(f"  currency:    {contract.currency}")
    finally:
        if ib.isConnected():
            ib.disconnect()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
