"""
Test connectivity to a running TWS/IB Gateway instance.

Usage:
  # With 1Password resolution (if BROKER_TWS_PORT uses op:// ref):
  op run --env-file=.env.dev -- uv run python scripts/test_tws_connection.py --env dev

  # Plain dotenv (if BROKER_TWS_PORT is a plain value):
  uv run python scripts/test_tws_connection.py --env dev
"""

import argparse
import os

from dotenv import load_dotenv
from ib_async import IB

from src.utils.env_vars import get_int_env


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def main():
    parser = argparse.ArgumentParser(description="Test TWS connection")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    load_env(args.env)

    host = "127.0.0.1"
    port = get_int_env("BROKER_TWS_PORT", 7497)

    print(f"Connecting to TWS at {host}:{port} ...")

    ib = IB()
    try:
        ib.connect(host, port, clientId=1)
        print("Connected successfully!")
        print()
        print(f"  Server version: {ib.client.serverVersion()}")

        accounts = ib.managedAccounts()
        for acct in accounts:
            print(f"  Account: {acct[:3]}{'*' * (len(acct) - 3)}")
            summary = ib.accountSummary(acct)
            for item in summary:
                if item.tag == "NetLiquidation":
                    print(f"  Net Liquidation: ${float(item.value):,.2f}")
                    break
    except Exception as e:
        print(f"Connection failed: {e}")
        raise SystemExit(1) from e
    finally:
        if ib.isConnected():
            ib.disconnect()
            print()
            print("Disconnected.")


if __name__ == "__main__":
    main()
