"""
Create the ngtrader database and run migrations.

Usage:
  uv run python scripts/setup_db.py --env dev
  op run --env-file=.env.dev -- uv run python scripts/setup_db.py --env dev
"""

import argparse
import os
import subprocess  # noqa: S404  # nosec B404
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def load_env(env_name: str) -> None:
    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        raise FileNotFoundError(f"{env_file} not found")
    load_dotenv(env_file)


def main():
    parser = argparse.ArgumentParser(description="Set up ngtrader database")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    args = parser.parse_args()

    load_env(args.env)

    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    db_name = os.environ.get("DB_NAME", "ngtrader_dev")

    # Connect to the maintenance database to create the target DB
    maintenance_url = f"postgresql://{user}:{password}@{host}:{port}/postgres"
    engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        )
        if result.fetchone():
            print(f"Database '{db_name}' already exists.")
        else:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
            print(f"Database '{db_name}' created.")

    engine.dispose()

    # Run alembic migrations
    print("Running migrations ...")
    result = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env={
            **os.environ,
            "DB_HOST": host,
            "DB_PORT": port,
            "DB_NAME": db_name,
            "DB_USER": user,
            "DB_PASSWORD": password,
        },
    )
    if result.returncode != 0:
        print("Migration failed!")
        raise SystemExit(1)

    print("Done. Database is ready.")


if __name__ == "__main__":
    main()
