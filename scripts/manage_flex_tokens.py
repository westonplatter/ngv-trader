"""Manage IBKR FlexQuery tokens stored encrypted in `flexquery_tokens`.

This is the only supported way to seed, inspect, retire, and re-key tokens.
The token value is never accepted as a command-line argument (argv reaches the
shell history and the process table) and is never printed back.

Usage:
    uv run python scripts/manage_flex_tokens.py list --env prod
    uv run python scripts/manage_flex_tokens.py deactivate --name main
    uv run python scripts/manage_flex_tokens.py verify
    uv run python scripts/manage_flex_tokens.py rotate-key
    uv run python scripts/manage_flex_tokens.py generate-key --out newkey.txt

Seeding a token — the value goes in over stdin, never as an argument:
    uv run python scripts/manage_flex_tokens.py add --name main --report-id 123456
        (prompts for the token; input is not echoed)
    op read op://ngtrader_pro/FLEX_TOKEN_MAIN/value | \
        uv run python scripts/manage_flex_tokens.py add --name main --report-id 123456
        (pipes it straight from 1Password, so it never hits the terminal)

Key rotation, end to end:
    1. generate-key --out <path>, and put the value in 1Password
    2. prepend it to FLEX_TOKEN_ENCRYPTION_KEY so the var reads "<new>,<old>"
    3. rotate-key   (re-encrypts every row under the new primary key)
    4. verify
    5. drop the old key from FLEX_TOKEN_ENCRYPTION_KEY
"""

from __future__ import annotations

import argparse
import getpass
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from src.db import get_engine
from src.models import Account, FlexQueryToken
from src.utils import crypto

TOKEN_VALUE_ENV_VAR = "FLEX_TOKEN_VALUE"  # noqa: S105  # nosec B105 — var name, not a secret


def _read_token_value() -> str:
    """Take the token from the environment, else prompt without echoing it."""
    from_env = os.environ.get(TOKEN_VALUE_ENV_VAR)
    if from_env and from_env.strip():
        return from_env.strip()
    if not sys.stdin.isatty():
        value = sys.stdin.readline().strip()
        if value:
            return value
        raise SystemExit(f"No token supplied. Set {TOKEN_VALUE_ENV_VAR} or pipe the value on stdin.")
    return getpass.getpass("FlexQuery token (not echoed): ").strip()


def cmd_add(engine: Engine, args: argparse.Namespace) -> int:
    # Resolve the key BEFORE reading the token. Encryption otherwise fails at
    # flush time, and SQLAlchemy wraps a bind-parameter failure in a
    # StatementError that echoes the parameters — which would put the plaintext
    # token in a traceback. Fail here, where no token exists yet.
    try:
        crypto.key_count()
    except crypto.EncryptionKeyError as exc:
        print(f"{exc}\n\nNothing was read or written.")
        return 1

    token_value = _read_token_value()
    if not token_value:
        print("Empty token — nothing written.")
        return 1

    now = datetime.now(timezone.utc)
    row = FlexQueryToken(
        name=args.name,
        token_encrypted=token_value,
        report_id=args.report_id,
        is_active=True,
        notes=args.notes,
        created_at=now,
        updated_at=now,
    )
    with Session(engine) as session:
        session.add(row)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            print(f"A token named {args.name!r} already exists. Pick another name, or deactivate that one first.")
            return 1
        except StatementError as exc:
            # Never surface `exc` itself — its message embeds the bound
            # parameters, one of which is the token.
            session.rollback()
            print(f"Insert failed ({type(exc.orig).__name__ if exc.orig else type(exc).__name__}). Nothing was written.")
            print("Details are suppressed because the failing statement carries the token value.")
            return 1
        print(f"Added token {args.name!r} (report_id={args.report_id}, fingerprint={crypto.fingerprint(token_value)}).")
    return 0


def cmd_list(engine: Engine, args: argparse.Namespace) -> int:
    with Session(engine) as session:
        rows = session.execute(select(FlexQueryToken).order_by(FlexQueryToken.id)).scalars().all()
        if not rows:
            print("No tokens configured.")
            return 0
        print(f"{'name':<20} {'report_id':<12} {'active':<7} {'accounts':<9} {'last_used_at':<28} fingerprint")
        for row in rows:
            stamped = session.execute(select(func.count()).select_from(Account).where(Account.flex_query_token_id == row.id)).scalar_one()
            last_used = row.last_used_at.isoformat() if row.last_used_at else "never"
            # Fingerprint, never the value — enough to tell two tokens apart.
            print(f"{row.name:<20} {row.report_id:<12} {str(row.is_active):<7} {stamped:<9} {last_used:<28} {crypto.fingerprint(row.token_encrypted)}")
    return 0


def cmd_deactivate(engine: Engine, args: argparse.Namespace) -> int:
    with Session(engine) as session:
        row = session.execute(select(FlexQueryToken).where(FlexQueryToken.name == args.name)).scalars().first()
        if row is None:
            print(f"No token named {args.name!r}.")
            return 1
        row.is_active = False
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        print(f"Deactivated {args.name!r}. Sync runs will now skip it.")
    return 0


def cmd_rotate_key(engine: Engine, args: argparse.Namespace) -> int:
    """Re-encrypt every stored token under the current primary key.

    This reads and writes the ciphertext through raw SQL rather than the ORM on
    purpose. The model attribute decrypts to the same plaintext before and after
    a rotation, so SQLAlchemy's change detection would see nothing to flush and
    silently write nothing at all.
    """
    now = datetime.now(timezone.utc)
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, name, token_encrypted FROM flexquery_tokens ORDER BY id")).all()
        if not rows:
            print("No tokens to rotate.")
            return 0
        for row in rows:
            rotated = crypto.rotate(row.token_encrypted)
            conn.execute(
                text("UPDATE flexquery_tokens SET token_encrypted = :ciphertext, updated_at = :updated_at WHERE id = :id"),
                {"ciphertext": rotated, "updated_at": now, "id": row.id},
            )
            print(f"  re-encrypted {row.name!r}")
    print(f"Rotated {len(rows)} token(s). Run `verify`, then drop the old key from {crypto.ENCRYPTION_KEY_ENV_VAR}.")
    return 0


def cmd_verify(engine: Engine, args: argparse.Namespace) -> int:
    """Prove the deployment end to end: key resolves, rows decrypt, disk is ciphertext."""
    try:
        count = crypto.key_count()
    except crypto.EncryptionKeyError as exc:
        print(f"FAIL  {exc}")
        return 1
    print(f"PASS  {crypto.ENCRYPTION_KEY_ENV_VAR} resolves ({count} key(s) configured)")

    failures = 0
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, name, token_encrypted FROM flexquery_tokens ORDER BY id")).all()
    if not rows:
        print("WARN  no tokens configured — nothing to decrypt. Seed one with `add`.")
        return 1

    for row in rows:
        try:
            plaintext = crypto.decrypt(row.token_encrypted)
        except crypto.DecryptionError as exc:
            print(f"FAIL  {row.name!r} does not decrypt: {exc}")
            failures += 1
            continue
        if plaintext == row.token_encrypted:
            print(f"FAIL  {row.name!r} is stored in plaintext")
            failures += 1
            continue
        print(f"PASS  {row.name!r} decrypts, stored value is ciphertext (fingerprint={crypto.fingerprint(plaintext)})")

    if failures:
        print(f"\n{failures} token(s) failed. Check that {crypto.ENCRYPTION_KEY_ENV_VAR} holds the key they were written under.")
        return 1
    print(f"\nAll {len(rows)} token(s) verified.")
    return 0


def cmd_generate_key(engine: Engine | None, args: argparse.Namespace) -> int:
    """Mint a Fernet key. Writes to a 0600 file unless --stdout is explicit.

    Printing key material puts it in terminal scrollback and any agent
    transcript, which is why stdout is opt-in rather than the default.
    """
    key = crypto.generate_key()
    if args.stdout:
        print(key)
        print("\nThat key is now in your terminal scrollback. Store it in 1Password and clear the buffer.", file=sys.stderr)
        return 0

    path = Path(args.out)
    path.write_text(key + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Wrote a new Fernet key to {path} (mode 0600).")
    print("Move it into 1Password, reference it from FLEX_TOKEN_ENCRYPTION_KEY, then delete the file.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --env is accepted on either side of the subcommand. SUPPRESS keeps the
    # subparser copy from clobbering a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--env", choices=["dev", "prod"], default=argparse.SUPPRESS, help="Env file to load (default: $ENV, else prod)")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, parents=[common])
    sub = parser.add_subparsers(dest="action", required=True)

    p_add = sub.add_parser("add", help="Create a token row", parents=[common])
    p_add.add_argument("--name", required=True, help="Operator label, unique")
    p_add.add_argument("--report-id", required=True, help="IBKR FlexQuery report id")
    p_add.add_argument("--notes", default=None)
    p_add.set_defaults(func=cmd_add)

    p_list = sub.add_parser("list", help="Show configured tokens (values are never printed)", parents=[common])
    p_list.set_defaults(func=cmd_list)

    p_deactivate = sub.add_parser("deactivate", help="Stop using a token without deleting it", parents=[common])
    p_deactivate.add_argument("--name", required=True)
    p_deactivate.set_defaults(func=cmd_deactivate)

    p_rotate = sub.add_parser("rotate-key", help="Re-encrypt every token under the current primary key", parents=[common])
    p_rotate.set_defaults(func=cmd_rotate_key)

    p_verify = sub.add_parser("verify", help="Check the key resolves and every stored token decrypts", parents=[common])
    p_verify.set_defaults(func=cmd_verify)

    p_generate = sub.add_parser("generate-key", help="Mint a new Fernet key")
    p_generate.add_argument("--out", default=None, help="File to write the key to, mode 0600")
    p_generate.add_argument("--stdout", action="store_true", help="Print the key instead (lands in scrollback)")
    p_generate.set_defaults(func=cmd_generate_key)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.action == "generate-key":
        if not args.out and not args.stdout:
            parser.error("generate-key needs --out <path> (recommended) or --stdout")
        return cmd_generate_key(None, args)

    env = getattr(args, "env", None) or os.environ.get("ENV", "prod")
    load_dotenv(f".env.{env}")
    return args.func(get_engine(), args)


if __name__ == "__main__":
    sys.exit(main())
