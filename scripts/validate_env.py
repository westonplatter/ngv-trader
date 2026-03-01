"""
Validate the development environment: env file, Postgres, migrations, and TWS.

Usage:
  uv run python scripts/validate_env.py --env dev
  uv run python scripts/validate_env.py --env dev --check-tws
  task validate
  task validate -- --check-tws

With 1Password (wrap externally):
  op run --env-file=.env.dev -- uv run python scripts/validate_env.py --env dev
"""

import argparse
import os
import sys

from dotenv import load_dotenv


# -- Utilities ----------------------------------------------------------------

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
SKIP = "\033[33mSKIP\033[0m"


def banner(title: str) -> None:
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def result(label: str, ok: bool, detail: str = "") -> bool:
    tag = PASS if ok else FAIL
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{tag}] {label}{suffix}")
    return ok


def skip(label: str, reason: str) -> None:
    print(f"  [{SKIP}] {label}  ({reason})")


# -- Checks -------------------------------------------------------------------


def check_env_file(env_name: str) -> bool:
    """Verify .env.<env> exists and required vars are set."""
    banner(f"1. Environment file (.env.{env_name})")

    env_file = f".env.{env_name}"
    if not os.path.exists(env_file):
        return result(
            f"{env_file} exists",
            False,
            f"File not found. Copy .env.example to {env_file} and fill in values.",
        )

    load_dotenv(env_file)
    file_ok = result(f"{env_file} exists", True)

    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER"]
    all_ok = file_ok
    for var in required:
        val = os.environ.get(var, "")
        if val and not val.startswith("op://"):
            all_ok = result(f"{var} is set", True) and all_ok
        elif val.startswith("op://"):
            all_ok = result(
                f"{var} is set",
                False,
                f"Contains op:// reference ({val}). "
                "Wrap with: op run --env-file=.env.dev -- <command>",
            ) and all_ok
        else:
            all_ok = result(f"{var} is set", False, "Empty or missing") and all_ok

    return all_ok


def check_postgres() -> bool:
    """Connect to PostgreSQL and verify the database exists."""
    banner("2. PostgreSQL connection")

    try:
        from sqlalchemy import text

        from src.db import get_engine
    except ImportError as exc:
        return result("Import sqlalchemy/src.db", False, str(exc))

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_name = os.environ.get("DB_NAME", "ngtrader_dev")
        return result(f"Connected to database '{db_name}'", True)
    except Exception as exc:
        msg = str(exc).split("\n")[0]
        return result("Connect to PostgreSQL", False, msg)


def check_migrations() -> bool:
    """Verify alembic migrations are up to date."""
    banner("3. Alembic migrations")

    try:
        from alembic import command
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import text

        from src.db import get_engine
    except ImportError as exc:
        return result("Import alembic", False, str(exc))

    try:
        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        engine = get_engine()
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            current_rev = row[0] if row else None

        if current_rev == head_rev:
            return result("Migrations up to date", True, f"at {current_rev[:12]}")
        elif current_rev is None:
            return result(
                "Migrations up to date",
                False,
                "No alembic_version found. Run: task migrate",
            )
        else:
            return result(
                "Migrations up to date",
                False,
                f"DB at {current_rev[:12]}, head is {head_rev[:12]}. Run: task migrate",
            )
    except Exception as exc:
        msg = str(exc).split("\n")[0]
        return result("Check migration status", False, msg)


def check_tws() -> bool:
    """Test connectivity to TWS / IB Gateway."""
    banner("4. TWS / IB Gateway")

    try:
        from ib_async import IB

        from src.utils.env_vars import get_int_env
    except ImportError as exc:
        return result("Import ib_async", False, str(exc))

    host = "127.0.0.1"
    port = get_int_env("BROKER_TWS_PORT", 7497)

    print(f"  Connecting to {host}:{port} ...")
    ib = IB()
    try:
        ib.connect(host, port, clientId=99, timeout=5)
        version = ib.client.serverVersion()
        ib.disconnect()
        return result(f"Connected to TWS (server v{version})", True)
    except Exception as exc:
        msg = str(exc).split("\n")[0]
        return result(
            "Connect to TWS/Gateway",
            False,
            f"{msg}. Is TWS/Gateway running with API enabled on port {port}?",
        )


# -- Main ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the ngtrader development environment"
    )
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument(
        "--check-tws",
        action="store_true",
        help="Also test TWS/IB Gateway connectivity",
    )
    args = parser.parse_args()

    print(f"\nValidating environment: {args.env}")

    passed = 0
    failed = 0

    checks = [
        ("env file", lambda: check_env_file(args.env)),
        ("postgres", check_postgres),
        ("migrations", check_migrations),
    ]

    for _name, check_fn in checks:
        if check_fn():
            passed += 1
        else:
            failed += 1

    if args.check_tws:
        if check_tws():
            passed += 1
        else:
            failed += 1
    else:
        banner("4. TWS / IB Gateway")
        skip("TWS connectivity", "pass --check-tws to enable")

    # Summary
    banner("Summary")
    total = passed + failed
    print(f"  {passed}/{total} checks passed")
    if failed:
        print(f"  {failed} check(s) failed — see details above")
        sys.exit(1)
    else:
        print("  Environment looks good!")


if __name__ == "__main__":
    main()
