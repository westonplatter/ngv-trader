"""Self-contained tests for the `add_meta_yaml_to_trade_groups` Alembic migration.

No DB connection required — the migration module is loaded by file path (its
filename starts with a timestamp, so it isn't a valid dotted-import target) and
`alembic.op` is mocked to capture the DDL calls `upgrade()`/`downgrade()` would
issue. Run with:

    uv run python scripts/test_add_meta_yaml_migration.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

_MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "20260711015301_add_meta_yaml_to_trade_groups.py"
)


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("add_meta_yaml_to_trade_groups", _MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_migration = _load_migration_module()


def test_revision_metadata() -> None:
    assert _migration.revision == "a3bf4e84435e"
    assert _migration.down_revision == "01711d684634"
    assert _migration.branch_labels is None
    assert _migration.depends_on is None


def test_upgrade_adds_nullable_text_column() -> None:
    with patch("alembic.op.add_column") as mock_add_column:
        _migration.upgrade()

    assert mock_add_column.call_count == 1
    (table_name, column), _kwargs = mock_add_column.call_args
    assert table_name == "trade_groups"
    assert isinstance(column, sa.Column)
    assert column.name == "meta_yaml"
    assert isinstance(column.type, sa.Text)
    assert column.nullable is True


def test_downgrade_drops_column() -> None:
    with patch("alembic.op.drop_column") as mock_drop_column:
        _migration.downgrade()

    mock_drop_column.assert_called_once_with("trade_groups", "meta_yaml")


def test_upgrade_and_downgrade_are_independent() -> None:
    # Calling one should never touch the other's operation.
    with patch("alembic.op.add_column") as mock_add_column, patch("alembic.op.drop_column") as mock_drop_column:
        _migration.upgrade()
        assert mock_add_column.called
        assert not mock_drop_column.called

    with patch("alembic.op.add_column") as mock_add_column, patch("alembic.op.drop_column") as mock_drop_column:
        _migration.downgrade()
        assert mock_drop_column.called
        assert not mock_add_column.called


def test_model_column_matches_migration_shape() -> None:
    """The TradeGroup ORM column should mirror what this migration adds."""
    from src.models import TradeGroup

    column = TradeGroup.__table__.columns["meta_yaml"]
    assert isinstance(column.type, sa.Text)
    assert column.nullable is True


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())