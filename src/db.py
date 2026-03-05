"""Shared DB engine helper."""

import os
from functools import cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_database_url(db_name: str | None = None) -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    name = db_name or os.environ.get("DB_NAME", "ngtrader_dev")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


@cache
def get_engine(db_name: str | None = None) -> Engine:
    return create_engine(
        get_database_url(db_name),
        pool_pre_ping=True,
        pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
        max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "10")),
        pool_timeout=int(os.environ.get("DB_POOL_TIMEOUT_SECONDS", "30")),
    )
