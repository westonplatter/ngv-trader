"""FastAPI dependencies for database access."""

from collections.abc import Generator

from sqlalchemy.orm import Session

from src.db import get_engine


def get_db() -> Generator[Session, None, None]:
    engine = get_engine()
    with Session(engine) as session:
        yield session
