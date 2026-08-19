# uv adapter notes

## Cooldown is manual — nothing enforces it

Unlike bun, `uv` has no `minimumReleaseAge`. The policy lives in a flag someone
has to remember:

```bash
uv add <pkg> --exclude-newer "$(date -u -d '14 days ago' +%Y-%m-%d)"
```

Dependabot's own `cooldown: default-days: 14` covers the PRs it opens, but not
a version you type by hand or pin transitively. Run
`check_cooldown.py --adapter uv '<pkg>==<version>'` before committing — it
reads the real upload date from PyPI.

## Python lives at `0.x`

`fastapi`, `pandera`, `mcp`, `ruff`, `typer` — a large share of the dependency
tree never reached 1.0, so "minor bump" carries no compatibility promise. These
are medium tier by rule, not by judgment call.

## The install line decides the import metric

`[tool.uv] default-groups = []` means a bare `uv sync` prunes the dev group and
the `mcp` extra. The adapter installs `uv sync --group dev --extra mcp`
deliberately: with the extra absent, `scripts/check.py` reports one failing
module and the baseline silently measures a different repo than CI does.

Same reason `pytest` runs as `uv run --group dev --extra mcp pytest`.

## Tests need a database and an env file

The suite connects to Postgres and reads `.env.dev` (see `tests/conftest.py`),
which is gitignored — so a baseline worktree has neither. The adapter's
`link_untracked` copies `.env.dev` in; without a reachable Postgres, drop the
metric: `--metrics imports,lint`.

## No local audit command

`uv` ships no `audit`. `audit_cmd` is `null` and that is honest: report that
Python vulnerabilities are covered by GitHub's Dependabot alerts, not by a
command you ran. Do not add `pip-audit` for a single batch — it is a new direct
dependency and falls under the cooldown itself.

## Transitive pins

`[tool.uv] constraint-dependencies` bounds an existing transitive dependency
without promoting it to a direct one. `override-dependencies` forces a version
against a parent's stated requirement — stronger, and more likely to produce a
resolution that never gets tested upstream. Prefer constraints.
