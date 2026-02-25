"""Environment variable parsing helpers."""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404  # nosec B404
from typing import overload


@overload
def get_int_env(name: str, default: int) -> int: ...


@overload
def get_int_env(name: str, default: None = None) -> int | None: ...


def get_int_env(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    if raw.startswith("op://"):
        raw = resolve_1password_reference(name, raw)

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got '{raw}'") from exc


@overload
def get_str_env(name: str, default: str) -> str: ...


@overload
def get_str_env(name: str, default: None = None) -> str | None: ...


def get_str_env(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default

    if raw.startswith("op://"):
        raw = resolve_1password_reference(name, raw)

    return raw.strip()


def resolve_1password_reference(name: str, reference: str) -> str:
    op_executable = shutil.which("op")
    if op_executable is None:
        raise ValueError(f"{name} uses 1Password reference '{reference}', but `op` CLI is not installed.")

    try:
        result = subprocess.run(  # noqa: S603  # nosec B603
            [op_executable, "read", reference],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        details = (exc.stderr or exc.stdout or "").strip()
        if details:
            raise ValueError(f"Could not resolve 1Password reference for {name} ('{reference}'): {details}") from exc
        raise ValueError(
            f"Could not resolve 1Password reference for {name} ('{reference}'). " "Run `op signin` or start with `op run --env-file=.env.dev -- <command>`."
        ) from exc

    resolved = result.stdout.strip()
    if not resolved:
        raise ValueError(f"1Password reference for {name} ('{reference}') resolved to an empty value.")
    return resolved
