"""Git worktree helpers: detect a linked worktree and name its test database.

Git isolates files per worktree, not databases. Giving each linked worktree its
own test database lets several agents run the suite at the same time. See
docs/contributing/worktrees.md.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

DEFAULT_TEST_DB_NAME = "ngv_trader_test"

_PREFIX = "ngv_trader_"
_SUFFIX = "_test"
# Postgres truncates identifiers past 63 bytes, which could cut the suffix off.
_MAX_SLUG_LENGTH = 63 - len(_PREFIX) - len(_SUFFIX)


def is_linked_worktree(repo_root: Path) -> bool:
    """True for a worktree made by `git worktree add`: its `.git` is a file, not a directory."""
    return (repo_root / ".git").is_file()


def worktree_test_db_name(repo_root: Path) -> str:
    """The shared test database in the main checkout, `ngv_trader_<dir>_test` in a linked worktree."""
    if not is_linked_worktree(repo_root):
        return DEFAULT_TEST_DB_NAME

    slug = re.sub(r"[^a-z0-9]+", "_", repo_root.name.lower()).strip("_")[:_MAX_SLUG_LENGTH].strip("_")
    if not slug:
        return DEFAULT_TEST_DB_NAME
    return f"{_PREFIX}{slug}{_SUFFIX}"


def resolve_test_db_name(repo_root: Path) -> str:
    """`TEST_DB_NAME` when set, else the name derived from the checkout. Refuses non-test names."""
    db_name = os.environ.get("TEST_DB_NAME") or worktree_test_db_name(repo_root)
    if not db_name.endswith(_SUFFIX):
        raise RuntimeError(f"refusing to run tests against non-test database {db_name!r}")
    return db_name
