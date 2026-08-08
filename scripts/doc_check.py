#!/usr/bin/env python3
"""
doc_check.py — Automated checks for the doc review process.

Runs the mechanical verifications from docs/doc-review.md so human review
can focus on correctness and architecture rather than broken references.

Usage:
    uv run python scripts/doc_check.py              # default checks
    uv run python scripts/doc_check.py --routes     # include undocumented-routes (informational)
    uv run python scripts/doc_check.py links tasks  # run specific checks only

Default checks: links, scripts, tasks, specs
Optional:       routes (informational — many routes are intentionally undocumented)

Exit 0 = clean, 1 = hard failures found, 2 = usage error.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER_DIR = ROOT / "src/api/routers"
SCRIPTS_DIR = ROOT / "scripts"
TASKFILE = ROOT / "Taskfile.yaml"

# ── doc collection ────────────────────────────────────────────────────────────


def collect_doc_files() -> list[Path]:
    files: set[Path] = {ROOT / "README.md", ROOT / "AGENTS.md"}
    for pattern in ("docs/*.md", "docs/**/*.md"):
        files.update(ROOT.glob(pattern))
    return sorted(f for f in files if f.exists())


# ── individual checks ─────────────────────────────────────────────────────────

Issue = tuple[str, str, str]  # (check_key, file_rel, detail)


def _strip_code(text: str) -> str:
    """Remove fenced code blocks and inline code spans so their content is not link-checked."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


def check_internal_links(doc_files: list[Path]) -> list[Issue]:
    """[text](relative/path) links must resolve to existing files."""
    issues: list[Issue] = []
    link_re = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
    for doc in doc_files:
        for m in link_re.finditer(_strip_code(doc.read_text())):
            raw = m.group(2)
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            path = raw.split("#")[0].strip()
            if not path:
                continue
            resolved = (doc.parent / path).resolve()
            if not resolved.exists():
                rel = str(resolved.relative_to(ROOT)) if ROOT in resolved.parents else str(resolved)
                issues.append(("links", str(doc.relative_to(ROOT)), f"'{raw}' → {rel} not found"))
    return issues


def _is_plan(doc: Path) -> bool:
    """`docs/plans/*.md` are dated historical artifacts (AGENTS.md), not current-state docs."""
    return doc.parent == ROOT / "docs" / "plans"


def check_script_paths(doc_files: list[Path]) -> list[Issue]:
    """Every scripts/<name> cited in current-state docs must exist on disk.

    Plans are exempt: they record what a script was called at the time, and may
    name scripts that were later renamed, moved to `tests/`, or never written.
    """
    issues: list[Issue] = []
    script_re = re.compile(r"scripts/([\w\-\.]+)")
    for doc in doc_files:
        if _is_plan(doc):
            continue
        for m in script_re.finditer(doc.read_text()):
            name = m.group(1)
            # Check root scripts/ and frontend/scripts/ (AGENTS.md documents both)
            if not (ROOT / "scripts" / name).exists() and not (ROOT / "frontend" / "scripts" / name).exists():
                issues.append(("scripts", str(doc.relative_to(ROOT)), f"scripts/{name}"))
    return issues


def check_task_commands(doc_files: list[Path]) -> list[Issue]:
    """Every `task <name>` cited in docs must exist in Taskfile.yaml."""
    taskfile_text = TASKFILE.read_text()
    defined_tasks = set(re.findall(r"^  ([\w:]+):", taskfile_text, re.MULTILINE))

    issues: list[Issue] = []
    task_re = re.compile(r"`task\s+([\w:]+)")
    for doc in doc_files:
        for m in task_re.finditer(doc.read_text()):
            name = m.group(1)
            if name not in defined_tasks:
                issues.append(("tasks", str(doc.relative_to(ROOT)), f"`task {name}` not in Taskfile.yaml"))
    return issues


def check_spec_banners(doc_files: list[Path]) -> list[Issue]:
    """Each spec-*.md must have a status banner in the first 5 lines."""
    issues: list[Issue] = []
    for doc in doc_files:
        if doc.name.startswith("spec-"):
            head = "\n".join(doc.read_text().splitlines()[:5]).lower()
            if "status" not in head:
                issues.append(("specs", str(doc.relative_to(ROOT)), "no status banner in first 5 lines"))
    return issues


def check_undocumented_routes(doc_files: list[Path]) -> list[Issue]:
    """Routes in src/api/routers/ not mentioned in any doc (informational)."""
    all_doc_text = "\n".join(f.read_text() for f in doc_files)
    route_re = re.compile(r'@router\.(get|post|put|patch|delete)\(["\']([^"\']+)["\']', re.IGNORECASE)

    issues: list[Issue] = []
    for router_file in sorted(ROUTER_DIR.glob("*.py")):
        if router_file.name == "__init__.py":
            continue
        for m in route_re.finditer(router_file.read_text()):
            method = m.group(1).upper()
            path = m.group(2)
            full = f"/api/v1{path}"
            if full not in all_doc_text and path not in all_doc_text:
                issues.append(("routes", router_file.name, f"{method} {full}"))
    return issues


# ── registry ──────────────────────────────────────────────────────────────────

CHECKS: dict[str, tuple] = {
    "links": (check_internal_links, "Internal links"),
    "scripts": (check_script_paths, "Script paths"),
    "tasks": (check_task_commands, "Task commands"),
    "specs": (check_spec_banners, "Spec status banners"),
    "routes": (check_undocumented_routes, "Undocumented routes (informational)"),
}

DEFAULT_CHECKS = {"links", "scripts", "tasks", "specs"}

# ── runner ────────────────────────────────────────────────────────────────────


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    include_routes = "--routes" in flags

    if args:
        unknown = set(args) - set(CHECKS)
        if unknown:
            print(f"Unknown checks: {', '.join(sorted(unknown))}. Valid: {', '.join(CHECKS)}", file=sys.stderr)
            sys.exit(2)
        active = set(args)
    else:
        active = DEFAULT_CHECKS | ({"routes"} if include_routes else set())

    doc_files = collect_doc_files()
    print(f"Checking {len(doc_files)} doc files...\n")

    all_issues: list[Issue] = []
    for key, (fn, label) in CHECKS.items():
        if key not in active:
            continue
        issues = fn(doc_files)
        status = f"✗  {len(issues)} issue(s)" if issues else "✓  clean"
        print(f"  {label:<42} {status}")
        all_issues.extend(issues)

    if not all_issues:
        print("\nAll checks passed.")
        return

    # ── report ────────────────────────────────────────────────────────────────
    print(f"\n{'─' * 70}")
    for check, file, detail in all_issues:
        severity = "WARN" if check == "routes" else "FAIL"
        print(f"[{severity}][{check}] {file}")
        print(f"       {detail}")

    hard = [i for i in all_issues if i[0] != "routes"]
    warn = [i for i in all_issues if i[0] == "routes"]

    print(f"\n{'─' * 70}")
    if hard:
        print(f"{len(hard)} hard failure(s)  |  {len(warn)} informational warning(s)")
        sys.exit(1)
    else:
        print(f"0 hard failures  |  {len(warn)} informational warning(s)")


if __name__ == "__main__":
    main()
