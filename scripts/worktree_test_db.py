"""Show or drop the test database that belongs to this git worktree.

Each linked worktree runs the suite against its own `ngv_trader_<dir>_test`
database (see docs/contributing/worktrees.md). Drop it before removing the
worktree; nothing else cleans it up.

Usage:
    uv run python scripts/worktree_test_db.py name
    uv run python scripts/worktree_test_db.py drop
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from src.db import get_database_url
from src.utils.worktree import DEFAULT_TEST_DB_NAME, resolve_test_db_name

REPO_ROOT = Path(__file__).resolve().parents[1]


def drop_database(db_name: str) -> None:
    """Drop `db_name`, closing any connections still open to it."""
    if not re.fullmatch(r"[a-z0-9_]+", db_name):
        raise SystemExit(f"Refusing to drop {db_name!r}: only lowercase letters, digits, and underscores are allowed.")

    admin_engine = create_engine(get_database_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    finally:
        admin_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Show or drop this worktree's test database")
    parser.add_argument("command", choices=["name", "drop"])
    args = parser.parse_args()

    # Same connection settings the test suite uses (tests/conftest.py).
    load_dotenv(REPO_ROOT / os.environ.get("TEST_ENV_FILE", ".env.dev"), override=True)
    db_name = resolve_test_db_name(REPO_ROOT)

    if args.command == "name":
        print(db_name)
        return

    if db_name == DEFAULT_TEST_DB_NAME:
        raise SystemExit(f"Refusing to drop {db_name!r}: it is the shared test database, not a worktree's own.")

    drop_database(db_name)
    print(f"Dropped test database '{db_name}'.")


if __name__ == "__main__":
    main()
