"""Every module under src/ must import — the canary for dependency bumps."""

import importlib
import pkgutil

import pytest


def _all_src_modules() -> list[str]:
    package = importlib.import_module("src")
    modules = ["src"]
    modules += [info.name for info in pkgutil.walk_packages(package.__path__, prefix="src.")]
    return sorted(modules)


@pytest.mark.parametrize("module", _all_src_modules())
def test_module_imports(module: str) -> None:
    importlib.import_module(module)
