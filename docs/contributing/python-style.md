---
topics: ["python", "style", "dependencies", "pandas"]
code_dirs_or_files:
  ["src/", "scripts/", "pyproject.toml", "frontend/bunfig.toml"]
description: Python conventions for this repo — uv, type hints, import placement, tqdm progress bars, the 14-day dependency cooldown (Python and bun), and pandas principles.
---

# Python Style

## Principles

1. **Use `uv run python`** — always execute Python via `uv run python ...` for consistent dependency management and virtual environment isolation.
2. **Type hints everywhere** — annotate function signatures and variables.
3. **Prefer standard library** — reach for third-party packages only when the stdlib falls short.
4. **Explicit over implicit** — make intent obvious; avoid magic methods and metaprogramming without a compelling reason.

## Code organization

- Always place imports at the top of the file.
- Never import packages inside functions.

## Verifying code

- Never run Python or shell to test code.
- Use Ruff for fast feedback during edits.
- Require Pyright to pass before declaring changes correct.
- Verify imports with `uv run python scripts/check.py <module>` — see [validation.md](validation.md).

## Progress bars

Use `tqdm` for user-facing scripts or long-running processes. Keep log statements
above the progress bar with `tqdm.write()` instead of `print()`:

```python
from tqdm import tqdm

for item in tqdm(items, desc="Processing"):
    tqdm.write(f"Processing {item.name}")
    process(item)
```

For logging-module integration, route records through `tqdm.write`:

```python
import logging
from tqdm import tqdm


class TqdmLoggingHandler(logging.Handler):
    def emit(self, record):
        tqdm.write(self.format(record))


logging.basicConfig(handlers=[TqdmLoggingHandler()], level=logging.INFO)
```

## Package installation cooldown

A **14-day cooldown** applies to all new dependencies (Python and JS) to avoid
ingesting freshly-published, potentially-compromised versions.

**Python (uv):** enforce the cutoff at add time:

```bash
uv add <pkg> --exclude-newer "$(date -u -d '14 days ago' +%Y-%m-%d)"
```

1. Applies to direct dependencies only; transitive upgrades pulled in by `uv sync` are exempt.
2. Note the cooldown and the release date in the PR description when adding a new package.

**Frontend (bun):** enforced mechanically — `frontend/bunfig.toml` sets
`minimumReleaseAge = 1209600` (14 days), so `bun add`/`bun install` refuse any
version published less than 14 days ago. No manual step needed. To intentionally
allow a fresh package, add it to `minimumReleaseAgeExcludes` in `bunfig.toml` and
note it in the PR.

This prevents ingesting packages with undetected supply-chain issues or breaking
changes in the days immediately after release.

## Pandas

1. **Use vectorized operations** — avoid `for` loops and `.iterrows()`.
2. **Chain methods** — `.pipe()`, `.assign()`, `.query()` for readable, declarative transformations.
3. **Be explicit with dtypes** — specify dtypes when reading data and enforce with `.astype()`.
4. **Prefer `.loc` and `.iloc`** — explicit indexing avoids `SettingWithCopyWarning` and chained-indexing surprises.
5. **Handle missing data intentionally** — `.isna()`, `.fillna()`, `.dropna()` explicitly; never assume data is complete.
6. **Use `.copy()` when needed** — copy subsets before modifying them to avoid mutating the original.
