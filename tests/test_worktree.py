"""Per-worktree test database naming (src/utils/worktree.py)."""

from pathlib import Path

import pytest

from src.utils.worktree import DEFAULT_TEST_DB_NAME, is_linked_worktree, resolve_test_db_name, worktree_test_db_name


def _main_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "ngv-trader"
    (root / ".git").mkdir(parents=True)
    return root


def _linked_worktree(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / ".git").write_text("gitdir: /somewhere/.git/worktrees/x\n")
    return root


def test_main_checkout_uses_the_shared_test_database(tmp_path: Path) -> None:
    root = _main_checkout(tmp_path)

    assert not is_linked_worktree(root)
    assert worktree_test_db_name(root) == DEFAULT_TEST_DB_NAME


def test_linked_worktree_gets_its_own_test_database(tmp_path: Path) -> None:
    root = _linked_worktree(tmp_path, "Fix-Roll.overlay")

    assert is_linked_worktree(root)
    assert worktree_test_db_name(root) == "ngv_trader_fix_roll_overlay_test"


def test_long_worktree_name_stays_within_the_postgres_identifier_limit(tmp_path: Path) -> None:
    name = worktree_test_db_name(_linked_worktree(tmp_path, "a" * 100))

    assert len(name) == 63
    assert name.endswith("_test")


def test_worktree_name_without_usable_characters_falls_back_to_shared(tmp_path: Path) -> None:
    assert worktree_test_db_name(_linked_worktree(tmp_path, "---")) == DEFAULT_TEST_DB_NAME


def test_explicit_test_db_name_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DB_NAME", "custom_test")

    assert resolve_test_db_name(_linked_worktree(tmp_path, "fix-roll")) == "custom_test"


def test_non_test_database_name_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_DB_NAME", "ngtrader_dev")

    with pytest.raises(RuntimeError, match="non-test database"):
        resolve_test_db_name(_main_checkout(tmp_path))


def test_derived_name_is_used_when_test_db_name_is_unset(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEST_DB_NAME", raising=False)

    assert resolve_test_db_name(_linked_worktree(tmp_path, "vol-surf")) == "ngv_trader_vol_surf_test"
