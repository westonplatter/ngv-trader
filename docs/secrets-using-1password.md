# 1Password Integration

This project uses [1Password CLI](https://developer.1password.com/docs/cli/) (`op`) to manage secrets in `.env` files.

## How it works

Environment files (`.env.dev`, `.env.prod`) can contain a mix of plain values and 1Password secret references. A secret reference uses the `op://` URI format:

```text
op://Vault/Item/Field
```

For example:

```bash
# Plain value
DB_HOST=127.0.0.1

# 1Password reference — resolved at runtime by `op run`
DB_PASSWORD=op://ngtr8der_dev/database/password
```

When you run a command with `op run --env-file=<file>`, the 1Password CLI:

1. Reads the env file
2. Resolves any `op://` references to actual secret values
3. Injects them as environment variables into the subprocess

## Prerequisites

1. Install the [1Password CLI](https://developer.1password.com/docs/cli/get-started/install/)
2. Sign in: `op signin`

## Usage

### Running scripts with resolved secrets

```bash
# Dev
op run --env-file=.env.dev -- uv run python scripts/example_env_vars.py --env dev

# Prod
op run --env-file=.env.prod -- uv run python scripts/example_env_vars.py --env prod
```

### Running without 1Password (plain dotenv only)

If you don't need 1Password resolution (e.g., no `op://` refs in your env file), you can run directly:

```bash
uv run python scripts/example_env_vars.py --env dev
```

Note: any `op://` values will remain as literal strings in this case.

## Code pattern

Use `load_dotenv` **without** `override=True` so it only fills in variables that aren't already set. This way, `op run` can inject resolved secrets first, and dotenv won't overwrite them:

```python
from dotenv import load_dotenv

load_dotenv(".env.dev")  # no override — respects existing env vars
```

See `scripts/example_env_vars.py` for a full working example.

## Adding new secrets

1. Add the variable to `.env.example` as a template
2. Add the plain or `op://` value to `.env.dev` and `.env.prod`
3. Access it in code with `os.environ.get("VAR_NAME")`
