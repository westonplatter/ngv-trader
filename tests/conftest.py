"""Pytest fixtures.

Mirrors the Rails `app_test` pattern: connection settings come from a normal
env file (`.env.dev` by default), but the database name is always overridden to
a dedicated test database that is created and migrated on demand.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[1]


def _configure_test_env() -> str:
    """Load connection settings, then force DB_NAME to the test database."""
    env_file = os.environ.get("TEST_ENV_FILE", ".env.dev")
    load_dotenv(REPO_ROOT / env_file, override=True)

    db_name = os.environ.get("TEST_DB_NAME", "ngv_trader_test")
    if not db_name.endswith("_test"):
        raise RuntimeError(f"refusing to run tests against non-test database {db_name!r}")

    os.environ["DB_NAME"] = db_name
    # alembic/env.py and src/api/main.py call load_dotenv(f".env.{ENV}"); point
    # them at a file that does not exist so they cannot clobber the settings above.
    os.environ["ENV"] = "test"
    return db_name


TEST_DB_NAME = _configure_test_env()


def _create_test_database_if_missing(db_name: str) -> None:
    from src.db import get_database_url

    admin_url = get_database_url("postgres")
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": db_name},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    finally:
        admin_engine.dispose()


def _migrate(db_name: str) -> None:
    from alembic import command
    from alembic.config import Config
    from src.db import get_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_database_url(db_name))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Session-scoped engine pointed at a freshly migrated test database."""
    from src.db import get_engine

    _create_test_database_if_missing(TEST_DB_NAME)
    _migrate(TEST_DB_NAME)
    yield get_engine(TEST_DB_NAME)


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    """A session whose writes are rolled back at the end of the test."""
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()
