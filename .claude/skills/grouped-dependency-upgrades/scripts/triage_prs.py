#!/usr/bin/env python3
"""Sort open bot dependency PRs into risk tiers, per ecosystem.

Reads PRs from `gh` when it exists, otherwise from JSON on stdin -- paste the
output of the GitHub MCP `list_pull_requests` tool, which is what web and
mobile sessions have instead of the CLI. Field names from either shape work.

Stdlib only: it must run in a fresh clone with no virtualenv synced.

Usage:
  triage_prs.py --repo owner/name                 # via gh
  triage_prs.py --from-file prs.json              # via MCP output
  cat prs.json | triage_prs.py --from-file -
  triage_prs.py --repo owner/name --json

Tiers (see references/triage.md):
  low     patch on >=1.0; dev-only or types minors  -> group into one PR
  medium  runtime minors; any 0.x minor; @types major; requirement widenings
          -> group into a SECOND PR, verified separately
  high    any major; anything in the adapter's toolchain list -> leave alone
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ADAPTER_DIR = SKILL_DIR / "adapters"

BUMP_RE = re.compile(
    r"bump\s+(?P<pkg>\S+)\s+from\s+(?P<old>\S+)\s+to\s+(?P<new>\S+)", re.IGNORECASE
)
WIDEN_RE = re.compile(
    r"update\s+(?P<pkg>\S+)\s+requirement\s+from\s+(?P<old>\S+)\s+to\s+(?P<new>\S+)",
    re.IGNORECASE,
)
BOTS = ("dependabot", "renovate")
TIER_ORDER = {"low": 0, "medium": 1, "high": 2, "unknown": 3}


def load_adapters() -> list[dict]:
    """`_*.json` are templates, not real ecosystems."""
    return [
        json.loads(p.read_text())
        for p in sorted(ADAPTER_DIR.glob("*.json"))
        if not p.name.startswith("_")
    ]


def gh_list(repo: str) -> list[dict]:
    cmd = ["gh", "pr", "list", "--limit", "100",
           "--json", "number,title,author,headRefName,labels"]
    if repo:
        cmd += ["--repo", repo]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"ERROR: gh failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def norm(pr: dict) -> dict:
    """Flatten gh and GitHub-MCP shapes into one record."""
    author = pr.get("author") or pr.get("user") or {}
    head = pr.get("head") or {}
    labels = [
        lbl if isinstance(lbl, str) else lbl.get("name", "")
        for lbl in (pr.get("labels") or [])
    ]
    return {
        "number": pr.get("number"),
        "title": html.unescape(pr.get("title", "")),
        "author": (author.get("login") or "").lower(),
        "branch": pr.get("headRefName") or head.get("ref") or "",
        "labels": labels,
    }


def is_bot(pr: dict) -> bool:
    """A dependency bot PR -- not merely a bot PR (release-please is not one)."""
    from_bot = any(bot in pr["author"] for bot in BOTS) or pr["branch"].startswith(
        ("dependabot/", "renovate/")
    )
    return from_bot and bool(BUMP_RE.search(pr["title"]) or WIDEN_RE.search(pr["title"]))


def ecosystem(pr: dict, adapters: list[dict]) -> str | None:
    """dependabot/<ecosystem>/<dir>/<pkg>-<version> -> adapter id."""
    parts = pr["branch"].split("/")
    raw = parts[1] if len(parts) > 2 and parts[0] in ("dependabot", "renovate") else None
    for adapter in adapters:
        aliases = adapter.get("dependabot_ecosystems", [adapter["id"]])
        if raw in aliases:
            return adapter["id"]
        if any(lbl in adapter.get("labels", []) for lbl in pr["labels"]):
            return adapter["id"]
    return raw


def nums(version: str) -> tuple[int, ...]:
    cleaned = re.sub(r"^[^0-9]*", "", version)
    parts = re.split(r"[.\-+]", cleaned)
    out: list[int] = []
    for part in parts[:3]:
        match = re.match(r"\d+", part)
        if not match:
            break
        out.append(int(match.group()))
    return tuple(out)


def bump_kind(old: str, new: str) -> str:
    a, b = nums(old), nums(new)
    if not a or not b:
        return "unknown"
    a = a + (0,) * (3 - len(a))
    b = b + (0,) * (3 - len(b))
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


def classify(pkg: str, old: str, kind: str, widening: bool, dev: bool,
             adapter: dict | None) -> tuple[str, str]:
    """First matching rule wins. Read top to bottom -- this is the tier policy."""
    cfg = adapter or {}
    is_types = pkg.startswith(tuple(cfg.get("types_prefixes", ["@types/"])))
    zero_ver = nums(old)[:1] == (0,)
    baseline_tool = pkg in cfg.get("baseline_tools", [])
    toolchain = pkg in cfg.get("toolchain", [])
    minor = kind == "minor"

    rules = [
        (widening, ("medium", "requirement floor widened; lock moves on next resolve")),
        (kind == "unknown", ("unknown", "could not parse versions from the title")),
        (toolchain and kind != "patch", ("high", "build toolchain package")),
        (kind == "major" and is_types,
         ("medium", "type-stub major: compile surface only, no runtime")),
        (kind == "major", ("high", "major bump")),
        # 0.x minors are not ordinary minors: semver lets 0.4 -> 0.5 break freely.
        (minor and zero_ver, ("medium", "0.x minor: semver allows breaking changes")),
        (minor and baseline_tool, ("medium", "moves the baseline it is measured against")),
        (minor and is_types, ("low", "type stubs")),
        (minor and dev, ("low", "dev-only minor")),
        (minor, ("medium", "runtime minor")),
        (baseline_tool,
         ("low", "patch; moves the baseline it is measured against -- read the diff")),
    ]
    for condition, result in rules:
        if condition:
            return result
    return "low", "patch"


def triage(pr: dict, adapters: list[dict]) -> dict:
    title = pr["title"]
    widening = False
    match = BUMP_RE.search(title)
    if not match:
        match = WIDEN_RE.search(title)
        widening = bool(match)
    eco = ecosystem(pr, adapters)
    adapter = next((a for a in adapters if a["id"] == eco), None)

    if not match:
        return {**pr, "ecosystem": eco, "package": None, "old": None, "new": None,
                "kind": "unknown", "tier": "unknown", "why": "unrecognized title"}

    if adapter is None:
        # classify() on an empty config silently loses this ecosystem's toolchain
        # and types_prefixes, so a toolchain major could land in a low batch --
        # and the branch name reads `chore/deps-None-low`. Route it to a human.
        return {**pr, "ecosystem": eco, "package": match.group("pkg"),
                "old": match.group("old"), "new": match.group("new"),
                "kind": "unknown", "tier": "unknown",
                "why": f"no adapter for ecosystem {eco!r}"}

    pkg, old, new = match.group("pkg"), match.group("old"), match.group("new")
    kind = "widen" if widening else bump_kind(old, new)
    dev = "deps-dev" in title
    tier, why = classify(pkg, old, kind, widening, dev, adapter)

    return {**pr, "ecosystem": eco, "package": pkg, "old": old, "new": new,
            "kind": kind, "tier": tier, "why": why}


def baseline_path() -> Path:
    """compare_baseline.py as typed from the repo root, where it will be run."""
    path = Path(__file__).resolve().parent / "compare_baseline.py"
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", help="owner/name; uses gh when available")
    parser.add_argument("--from-file", help="JSON file of PRs, or '-' for stdin")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    if args.from_file:
        text = sys.stdin.read() if args.from_file == "-" else Path(args.from_file).read_text()
        raw = json.loads(text)
    elif shutil.which("gh"):
        raw = gh_list(args.repo)
    else:
        sys.exit(
            "ERROR: no `gh` on PATH. Fetch the PRs with the GitHub MCP tool\n"
            "  list_pull_requests(state='open', fields=['number','title','user','labels','head'])\n"
            "then re-run with --from-file <saved.json> (or pipe it to --from-file -)."
        )

    adapters = load_adapters()
    prs = [triage(pr, adapters) for pr in map(norm, raw) if is_bot(pr)]
    prs.sort(key=lambda p: (p["ecosystem"] or "~", TIER_ORDER[p["tier"]], p["number"]))

    if args.as_json:
        print(json.dumps(prs, indent=2))
        return 0

    if not prs:
        print("No open bot dependency PRs.")
        return 0

    current = None
    for pr in prs:
        key = (pr["ecosystem"], pr["tier"])
        if key != current:
            current = key
            action = {
                "low": "group into one PR",
                "medium": "group into a SECOND PR, verified separately",
                "high": "leave the individual PR open",
                "unknown": "read the PR by hand",
            }[pr["tier"]]
            print(f"\n[{pr['ecosystem']}] {pr['tier'].upper()} -- {action}")
            if pr["tier"] in ("low", "medium"):
                print(f"  branch: chore/deps-{pr['ecosystem']}-{pr['tier']}")
        print(f"  #{pr['number']:<5} {pr['package'] or pr['title'][:40]:<32} "
              f"{(pr['old'] or '?')} -> {(pr['new'] or '?'):<12} ({pr['kind']}: {pr['why']})")

    print("\nNever group across ecosystems: separate lockfiles, separate revert blast radius.")
    print(f"Next: record the baseline BEFORE branching -> {baseline_path()} --adapter <id>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
