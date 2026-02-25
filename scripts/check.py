"""Quick compile/import checker for validating Python modules.

Usage:
    uv run python scripts/check.py                          # check all src/ modules
    uv run python scripts/check.py src.services.jobs         # check one module
    uv run python scripts/check.py src.models src.schemas    # check several modules
"""

import importlib
import pkgutil
import sys

import typer

app = typer.Typer(help="Validate that Python modules compile and import successfully.")


def discover_modules(package_name: str = "src") -> list[str]:
    """Walk the src package tree and return all importable module paths."""
    package = importlib.import_module(package_name)
    modules = [package_name]
    if hasattr(package, "__path__"):
        for info in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            modules.append(info.name)
    return sorted(modules)


def check_module(module: str) -> bool:
    """Try to import a single module. Returns True on success."""
    try:
        importlib.import_module(module)
        typer.echo(f"  OK    {module}")
        return True
    except Exception as e:
        typer.echo(f"  FAIL  {module}: {e}")
        return False


@app.command()
def main(
    modules: list[str] = typer.Argument(
        default=None,
        help="Module paths to check (e.g. src.models). Omit to check all src/ modules.",
    ),
) -> None:
    """Import one or more Python modules to verify they compile and run."""
    targets = modules if modules else discover_modules()

    passed = 0
    failed = 0
    for mod in targets:
        if check_module(mod):
            passed += 1
        else:
            failed += 1

    typer.echo("")
    typer.echo(f"Results: {passed} passed, {failed} failed out of {passed + failed} modules")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    app()
