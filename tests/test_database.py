"""Database wiring: the test DB exists, is migrated, and is not dev/prod."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def test_connects_to_the_test_database(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
        db_name = conn.execute(text("SELECT current_database()")).scalar()
    assert isinstance(db_name, str) and db_name.endswith("_test")


def test_migrations_applied(engine: Engine) -> None:
    """Alembic ran to head and the core tables exist."""
    with engine.connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert revision

    tables = set(inspect(engine).get_table_names())
    assert {"accounts", "positions", "trades", "trade_executions", "tags"} <= tables


def test_models_metadata_matches_migrated_tables(engine: Engine) -> None:
    """Every model table declared in src/models.py exists in the migrated DB."""
    from src.models import Base

    tables = set(inspect(engine).get_table_names())
    missing = sorted(set(Base.metadata.tables) - tables)
    assert not missing, f"tables missing from migrations: {missing}"
