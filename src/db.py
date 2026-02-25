"""Shared DB engine helper."""

import os

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def get_database_url(db_name: str | None = None) -> str:
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    name = db_name or os.environ.get("DB_NAME", "ngtrader_dev")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def get_engine(db_name: str | None = None) -> Engine:
    return create_engine(get_database_url(db_name))
