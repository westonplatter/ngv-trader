"""
Download current positions from IBKR TWS and store in Postgres.

Usage:
  op run --env-file=.env.dev -- uv run python scripts/download_positions.py --env dev
"""

import argparse
import os

from dotenv import load_dotenv

from src.db import get_engine
from src.services.position_sync import check_positions_tables_ready, sync_positions_once
from src.utils.env_vars import get_int_env


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def main():
    parser = argparse.ArgumentParser(description="Download IBKR positions to DB")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    load_env(args.env)

    engine = get_engine()
    check_positions_tables_ready(engine)

    host = "127.0.0.1"
    port = get_int_env("BROKER_TWS_PORT", 7497)
    client_id = 2

    print(f"Connecting to TWS at {host}:{port} ...")
    try:
        saved_count = sync_positions_once(
            engine=engine,
            host=host,
            port=port,
            client_id=client_id,
            connect_timeout_seconds=20.0,
        )
        print(f"Saved {saved_count} position(s) to database.")
    except Exception as e:
        print(f"Error: {e}")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
