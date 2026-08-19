#!/usr/bin/env python3
"""Compare repo health metrics against a base ref, driven by an ecosystem adapter.

Most repos do not gate every check in CI, so the bar for a dependency PR is
"unchanged", not "green". This measures both sides and diffs the counts.

The baseline is a detached git worktree -- never `git stash`, which silently
applies an unrelated stale stash when the tree is clean.

Stdlib only: it must run in a fresh clone with no virtualenv synced.

Usage:
  compare_baseline.py --list
  compare_baseline.py --adapter bun
  compare_baseline.py --adapter uv --base origin/main --metrics imports,lint
  compare_baseline.py --adapter bun --current-only --json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ADAPTER_DIR = SKILL_DIR / "adapters"
DEFAULT_TIMEOUT = 900


def load_adapter(name: str) -> dict:
    path = Path(name) if name.endswith(".json") else ADAPTER_DIR / f"{name}.json"
    if not path.exists():
        sys.exit(f"ERROR: no adapter at {path}. Try --list.")
    return json.loads(path.read_text())


def adapter_files() -> list[Path]:
    """`_*.json` are templates, not real ecosystems."""
    return [p for p in sorted(ADAPTER_DIR.glob("*.json")) if not p.name.startswith("_")]


def list_adapters() -> None:
    for path in adapter_files():
        cfg = json.loads(path.read_text())
        metrics = ",".join(m["name"] for m in cfg.get("metrics", [])) or "-"
        print(f"{cfg['id']:<16} dir={cfg.get('dir', '.'):<12} metrics={metrics}")


def sh(cmd: str, cwd: Path, timeout: int) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 124, f"TIMEOUT after {timeout}s"
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def score(metric: dict, code: int, out: str) -> int:
    """Reduce a command's output to one lower-is-better integer."""
    mode = metric.get("mode", "count")
    if mode == "status":
        return 0 if code == 0 else 1
    pattern = metric["pattern"]
    if mode == "count":
        return len(re.findall(pattern, out, re.MULTILINE))
    if mode == "capture":
        match = re.search(pattern, out, re.MULTILINE)
        return int(match.group(1)) if match else 0
    raise ValueError(f"unknown metric mode: {mode}")


def measure(root: Path, adapter: dict, wanted: list[str], label: str) -> dict[str, int | None]:
    work = root / adapter.get("dir", ".")
    metrics = [m for m in adapter.get("metrics", []) if m["name"] in wanted]
    if not work.is_dir():
        return {m["name"]: None for m in metrics}

    install = adapter.get("install")
    if install:
        print(f"  [{label}] {install}", file=sys.stderr)
        code, out = sh(install, work, adapter.get("install_timeout", DEFAULT_TIMEOUT))
        if code != 0:
            print(f"  [{label}] WARNING: install exited {code}", file=sys.stderr)
            print("  " + out.strip()[-500:], file=sys.stderr)

    results: dict[str, int | None] = {}
    for metric in metrics:
        print(f"  [{label}] {metric['cmd']}", file=sys.stderr)
        code, out = sh(metric["cmd"], work, metric.get("timeout", DEFAULT_TIMEOUT))
        results[metric["name"]] = score(metric, code, out)
    return results


def verdict(base: int | None, cur: int | None) -> str:
    if base is None or cur is None:
        return "n/a"
    if base == cur:
        return "same"
    if cur < base:
        return f"BETTER (-{base - cur})"
    return f"WORSE (+{cur - base})"


def git_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True
    )
    return Path(out.stdout.strip())


def carry_untracked(repo_root: Path, worktree: Path, adapter: dict) -> None:
    """A worktree is a clean checkout: gitignored config the checks need
    (env files, local settings) is absent and must be carried over."""
    for rel in adapter.get("link_untracked", []):
        src = repo_root / rel
        if not src.exists():
            print(f"  [base] WARNING: {rel} missing; metrics may not be comparable",
                  file=sys.stderr)
            continue
        dst = worktree / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  [base] carried over {rel}", file=sys.stderr)


def measure_baseline(repo_root: Path, adapter: dict, wanted: list[str],
                     base: str) -> dict[str, int | None]:
    subprocess.run(["git", "-C", str(repo_root), "fetch", "-q", "origin"], check=False)
    worktree = Path(tempfile.mkdtemp()) / "baseline"
    add = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "--detach", "-q", str(worktree), base],
        capture_output=True, text=True,
    )
    if add.returncode != 0:
        sys.exit(f"ERROR: could not create worktree at '{base}'.\n{add.stderr}")
    try:
        carry_untracked(repo_root, worktree, adapter)
        print(f"Measuring baseline at {base}...", file=sys.stderr)
        return measure(worktree, adapter, wanted, "base")
    finally:
        subprocess.run(
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(worktree)],
            capture_output=True,
        )


def render(base_label: str, wanted: list[str], base_results: dict, cur_results: dict) -> None:
    fmt = "%-18s %12s %12s   %s"
    print()
    print(fmt % ("metric", base_label, "working", "verdict"))
    print(fmt % ("-" * 18, "-" * 12, "-" * 12, "-------"))
    for name in wanted:
        base_val, cur_val = base_results[name], cur_results[name]
        print(fmt % (name,
                     "n/a" if base_val is None else base_val,
                     "n/a" if cur_val is None else cur_val,
                     verdict(base_val, cur_val)))
    print()


def resolve_metrics(adapter: dict, requested: str | None) -> list[str]:
    known = [m["name"] for m in adapter.get("metrics", [])]
    wanted = requested.split(",") if requested else known
    unknown = [n for n in wanted if n not in known]
    if unknown:
        sys.exit(f"ERROR: unknown metric(s) {unknown}; adapter has {known}")
    return wanted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", help="adapter id (see --list) or path to a .json")
    parser.add_argument("--base", default="origin/main", help="baseline ref")
    parser.add_argument("--metrics", help="comma-separated subset; default all")
    parser.add_argument("--current-only", action="store_true", help="skip the baseline worktree")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--list", action="store_true", help="list adapters and exit")
    args = parser.parse_args()
    if not args.list and not args.adapter:
        parser.error("--adapter is required (or --list)")
    return args


def main() -> int:
    args = parse_args()
    if args.list:
        list_adapters()
        return 0

    adapter = load_adapter(args.adapter)
    if not adapter.get("metrics"):
        print(f"Adapter '{adapter['id']}' declares no local metrics -- there is no offline "
              "health check for it.")
        print("Verify these bumps by the PR's own CI run instead.")
        return 0

    wanted = resolve_metrics(adapter, args.metrics)
    repo_root = git_root()
    work_dir = repo_root / adapter.get("dir", ".")

    base_results: dict[str, int | None] = {name: None for name in wanted}
    if not args.current_only:
        base_results = measure_baseline(repo_root, adapter, wanted, args.base)

    print("Measuring working tree...", file=sys.stderr)
    cur_results = measure(repo_root, adapter, wanted, "work")

    # The baseline installed from the base ref's lockfile in its own dir, but
    # restore the working tree's dependencies explicitly.
    install = adapter.get("install")
    if install and not args.current_only:
        sh(install, work_dir, adapter.get("install_timeout", DEFAULT_TIMEOUT))

    regressed = [
        name for name in wanted
        if base_results[name] is not None and cur_results[name] is not None
        and cur_results[name] > base_results[name]
    ]

    if args.as_json:
        print(json.dumps({"adapter": adapter["id"], "base": args.base,
                          "baseline": base_results, "current": cur_results,
                          "regressed": regressed}, indent=2))
    else:
        render(args.base, wanted, base_results, cur_results)

    if regressed:
        print(f"REGRESSION in {regressed} vs {args.base}. Do not ship.")
        return 1
    if args.current_only:
        print("Recorded current counts only (no baseline compared).")
        return 0
    print(f"OK: no regression vs {args.base}. Cite these counts in the PR body.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
