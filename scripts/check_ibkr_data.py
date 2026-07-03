"""Scan git-tracked files for real IBKR personal data that must not be committed.

High-signal identifier scan, aligned with `prompts/prompt-ibkr-sample-data.md`.
It flags account IDs and execution/brokerage IDs that are NOT the documented
placeholder forms — the values most likely to leak a real trading identity.

Numeric-only IDs (conId, tradeID, permId) are intentionally NOT scanned: real
values are indistinguishable from the generic placeholder ranges, so flagging
them would be pure noise. Guard those in review.

By default it scans everything `git ls-files` reports, so gitignored real data
under `scripts/data/` is skipped automatically. Pass explicit paths (e.g. from a
pre-commit hook) to scan just those.

Usage:
    uv run python scripts/check_ibkr_data.py               # scan all tracked files
    uv run python scripts/check_ibkr_data.py path/a path/b  # scan given paths

Exits 1 if anything is flagged.
"""

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import typer

app = typer.Typer(help="Flag real IBKR personal data that should not be in the repo.")

# Files that legitimately contain real-looking example values (the anonymization
# standard itself shows a "before" sample) — never flag these.
SKIP_PATHS = {
    "prompts/prompt-ibkr-sample-data.md",
    "scripts/check_ibkr_data.py",
}

# Documented placeholder account bodies (the 7 digits after an optional U/DU
# prefix) — everything else U/DU-shaped is flagged.
ALLOWED_ACCOUNT_BODIES = {"1234567", "9999999", "0000000"}


def _account_violation(value: str) -> bool:
    return value.lstrip("DU") not in ALLOWED_ACCOUNT_BODIES


def _ib_id_violation(value: str) -> bool:
    # Placeholder exec/brokerage IDs start with `00` (`0000abcd…`, `00aabbcc…`).
    # Real IB hex IDs effectively never do, so anything else is suspect.
    return not value.startswith("00")


# (label, regex, is_violation). Regexes are matched per line; the predicate
# decides whether a given match is a real value vs. an allowed placeholder.
DETECTORS: list[tuple[str, re.Pattern[str], Callable[[str], bool]]] = [
    ("account id", re.compile(r"\b(?:DU|U)\d{7}\b"), _account_violation),
    (
        "execution/brokerage id",
        re.compile(r"\b[0-9a-f]{6,8}(?:\.[0-9a-f]{6,8}){1,2}\.\d{2,3}\b"),
        _ib_id_violation,
    ),
]


def tracked_files() -> list[str]:
    """Return repo-relative paths of all git-tracked files."""
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def scan_file(path: str) -> list[tuple[int, str, str]]:
    """Return (line_no, label, value) for each flagged match in one file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return []  # binary or unreadable — nothing to scan

    findings: list[tuple[int, str, str]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for label, regex, is_violation in DETECTORS:
            for match in regex.findall(line):
                if is_violation(match):
                    findings.append((line_no, label, match))
    return findings


@app.command()
def main(
    paths: list[str] = typer.Argument(  # noqa: B008
        default=None,
        help="Files to scan. Omit to scan all git-tracked files.",
    ),
) -> None:
    """Scan for real IBKR account/execution identifiers and report any hits."""
    targets = paths if paths else tracked_files()

    total = 0
    for path in targets:
        if path in SKIP_PATHS:
            continue
        for line_no, label, value in scan_file(path):
            typer.echo(f"  {path}:{line_no}  {label}: {value}")
            total += 1

    typer.echo("")
    if total:
        typer.echo(f"FAIL: {total} possible real IBKR value(s) found.")
        typer.echo("Anonymize per prompts/prompt-ibkr-sample-data.md before committing.")
        raise SystemExit(1)
    typer.echo("OK: no real IBKR identifiers found in scanned files.")


if __name__ == "__main__":
    app()
