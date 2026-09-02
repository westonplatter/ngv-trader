#!/usr/bin/env python3
"""Check that a package version is older than the supply-chain cooldown.

Some ecosystems enforce a cooldown mechanically (bun's `minimumReleaseAge`);
most do not -- `uv add --exclude-newer` is a flag a human has to remember, and
a transitive pin (npm `overrides`, uv `constraint-dependencies`) bypasses the
mechanical check entirely. This asks the registry when a version was published.

Stdlib only: it must run in a fresh clone with no virtualenv synced.

Usage:
  check_cooldown.py --registry npm  react-plotly.js@4.1.0 ai@7.0.52
  check_cooldown.py --registry pypi alembic==1.19.0 fastapi==0.141.1
  check_cooldown.py --adapter bun --days 14 picomatch@4.0.5
  check_cooldown.py --registry pypi --json alembic==1.19.0

Exits 1 if any version is inside the cooldown window.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ADAPTER_DIR = SKILL_DIR / "adapters"
DEFAULT_DAYS = 14
UA = "grouped-dependency-upgrades/1.0 (+cooldown check)"


def ssl_context() -> ssl.SSLContext:
    """Honor an explicit CA bundle (agent proxies MITM TLS); never skip verify."""
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    if bundle and Path(bundle).exists():
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
        return json.loads(resp.read().decode())


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
        return resp.read().decode()


def parse_ts(value: str) -> datetime:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def published_npm(pkg: str, version: str) -> datetime:
    data = fetch_json(f"https://registry.npmjs.org/{urllib.parse.quote(pkg, safe='@')}")
    times = data.get("time", {})
    if version not in times:
        raise LookupError(f"{pkg}@{version} not published")
    return parse_ts(times[version])


def published_pypi(pkg: str, version: str) -> datetime:
    data = fetch_json(f"https://pypi.org/pypi/{urllib.parse.quote(pkg)}/{urllib.parse.quote(version)}/json")
    uploads = [u["upload_time_iso_8601"] for u in data.get("urls", []) if u.get("upload_time_iso_8601")]
    if not uploads:
        raise LookupError(f"{pkg}=={version} has no upload timestamp")
    return min(parse_ts(u) for u in uploads)


def published_crates(pkg: str, version: str) -> datetime:
    data = fetch_json(f"https://crates.io/api/v1/crates/{urllib.parse.quote(pkg)}/versions")
    for entry in data.get("versions", []):
        if entry.get("num") == version:
            return parse_ts(entry["created_at"])
    raise LookupError(f"{pkg} {version} not found on crates.io")


def escape_go(path: str) -> str:
    """Go proxy paths are case-folded: every uppercase letter becomes `!` + lowercase.

    proxy.golang.org happens to answer the plain-lowercase path too, so this is
    protocol conformance rather than a fix for an observed 404 -- but a strict
    proxy (Athens, a private GOPROXY) resolves only the escaped form, and two
    modules differing in case share one lowercase path.
    See https://go.dev/ref/mod#goproxy-protocol.
    """
    return "".join(f"!{c.lower()}" if c.isupper() else c for c in path)


def published_go(module: str, version: str) -> datetime:
    path = escape_go(module)
    data = json.loads(fetch_text(f"https://proxy.golang.org/{path}/@v/{escape_go(version)}.info"))
    return parse_ts(data["Time"])


def published_rubygems(pkg: str, version: str) -> datetime:
    for entry in fetch_json(f"https://rubygems.org/api/v1/versions/{urllib.parse.quote(pkg)}.json"):
        if entry.get("number") == version:
            return parse_ts(entry["created_at"])
    raise LookupError(f"{pkg} {version} not found on rubygems.org")


REGISTRIES = {
    "npm": published_npm,
    "pypi": published_pypi,
    "crates": published_crates,
    "go": published_go,
    "rubygems": published_rubygems,
}


def split_spec(spec: str) -> tuple[str, str]:
    """Accept pkg@version (npm/go) and pkg==version (python)."""
    if "==" in spec:
        pkg, _, version = spec.partition("==")
    else:
        at = spec.rfind("@")
        if at <= 0:
            raise ValueError(f"cannot parse '{spec}'; use pkg@version or pkg==version")
        pkg, version = spec[:at], spec[at + 1:]
    pkg = pkg.split("[", 1)[0]  # drop python extras: pandera[pandas] -> pandera
    return pkg.strip(), version.strip()


def parse_args() -> tuple[argparse.Namespace, str]:
    """Resolve the registry and window, from flags or the adapter that declares them."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specs", nargs="+", help="pkg@version or pkg==version")
    parser.add_argument("--registry", choices=sorted(REGISTRIES))
    parser.add_argument("--adapter", help="adapter id; reads its `registry` field")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    registry = args.registry
    if not registry and args.adapter:
        cfg = json.loads((ADAPTER_DIR / f"{args.adapter}.json").read_text())
        registry = cfg.get("registry")
        args.days = cfg.get("cooldown", {}).get("days", args.days)
    if not registry:
        parser.error("pass --registry or an --adapter that declares one")
    # Checked after the adapter resolves, so an adapter's own `cooldown.days` is
    # covered too: a negative window puts the cutoff in the future and every
    # version ever published clears the check -- a silent pass, not an error.
    if args.days < 0:
        parser.error(f"--days must be >= 0, got {args.days}")
    return args, registry


def main() -> int:
    args, registry = parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows, failed = [], False

    for spec in args.specs:
        pkg, version = split_spec(spec)
        try:
            when = REGISTRIES[registry](pkg, version)
        except (urllib.error.URLError, LookupError, KeyError, ValueError) as exc:
            rows.append({"package": pkg, "version": version, "published": None,
                         "age_days": None, "status": f"UNKNOWN ({exc})"})
            failed = True
            continue
        age = (datetime.now(timezone.utc) - when).days
        ok = when <= cutoff
        failed = failed or not ok
        rows.append({"package": pkg, "version": version,
                     "published": when.date().isoformat(), "age_days": age,
                     "status": "ok" if ok else f"TOO NEW (< {args.days}d)"})

    if args.as_json:
        print(json.dumps({"registry": registry, "days": args.days, "results": rows}, indent=2))
    else:
        fmt = "%-34s %-14s %-12s %6s  %s"
        print(fmt % ("package", "version", "published", "age", "status"))
        print(fmt % ("-" * 34, "-" * 14, "-" * 12, "-" * 6, "-" * 6))
        for row in rows:
            print(fmt % (row["package"][:34], row["version"][:14],
                         row["published"] or "-",
                         "-" if row["age_days"] is None else f"{row['age_days']}d",
                         row["status"]))

    if failed:
        print(f"\nAt least one version is inside the {args.days}-day cooldown (or unresolvable).")
        print("Leave the finding open and say so in the PR. Do not add a cooldown exclusion.")
        return 1
    print(f"\nAll versions are older than {args.days} days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
