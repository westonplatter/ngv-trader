# uv adapter notes

Everything below was measured in this repo, not read off the docs.

## Which command to bump with

Match the command to what the PR actually changes — the two title grammars in
[triage.md](triage.md) map straight onto them:

| PR shape | Command |
| --- | --- |
| `bump X from a to b` on a **dev-group** package | `uv add --group dev 'X==b'` |
| `bump X from a to b` on a **runtime** package | `uv add 'X==b'` |
| lock-only move, manifest floor already fits | `uv lock --upgrade-package X==b` |
| `update X requirement from >=a to >=b` | edit the floor in `pyproject.toml`, then `uv lock` |

**Omit `--group dev` on a dev tool and uv writes it into
`[project.dependencies]` as a runtime dependency**, leaving the real entry
untouched in the dev group. Measured: `uv add 'typer==0.27.1'` appended
`"typer==0.27.1"` to the runtime list while `"typer>=0.27.0"` stayed in
`[dependency-groups] dev`. Always diff `pyproject.toml` before staging.

## Never pass `--exclude-newer` when bumping an existing lock

It re-resolves the entire graph against the cutoff instead of moving one
package. Measured on a single dev patch bump:

| Command | Packages whose version moved |
| --- | --- |
| `uv add --group dev 'typer==0.27.1'` | 1 |
| `uv lock --upgrade-package 'typer==0.27.1'` | 1 |
| the same, plus `--exclude-newer <date>` | **94** — uvicorn, pandas, mcp, langsmith, ipython… |

A "low-risk dev patch bump" PR would have carried ~47 unrelated upgrades. The
flag is right where AGENTS.md uses it — `uv add` for a **brand-new**
dependency, where a full resolve is expected anyway — and wrong on a bump.

For the cooldown on a bump, check the date instead:

```bash
check_cooldown.py --adapter uv 'ruff==0.16.1'
```

## Confirm the blast radius after every bump

```bash
git diff uv.lock | grep -c '^+version = '     # should equal the number of packages you bumped
```

Verified good case: `uv add --group dev 'ruff==0.16.1'` → exactly 1 version
line, 27 lock lines (its wheel hashes), one `pyproject.toml` line.

## Python lives at `0.x`

`fastapi`, `pandera`, `mcp`, `ruff`, `typer` — a large share of the dependency
tree never reached 1.0, so "minor bump" carries no compatibility promise. These
are medium tier by rule, not by judgment call.

## The install line decides the import metric

`[tool.uv] default-groups = []` means a bare `uv sync` prunes the dev group and
the `mcp` extra. The adapter installs `uv sync --group dev --extra mcp`
deliberately: with the extra absent, `scripts/check.py` reports one failing
module and the baseline measures a different repo than CI does.

## Tests need a database and an env file

The suite connects to Postgres and reads `.env.dev` (see `tests/conftest.py`),
which is gitignored — so a baseline worktree has neither. The adapter's
`link_untracked` copies `.env.dev` in and warns when it is absent.

With no Postgres reachable, pytest never reaches a test body. The `tests`
metric then reports **UNMEASURABLE**, not 0 — deliberately. Its pattern is
anchored to pytest's summary line for the same reason: an unanchored
`([0-9]+) failed` matches `port 5432 failed: Connection refused` and reports a
tidy, meaningless `5432` on both sides. Drop the metric with
`--metrics imports,lint` and say so in the PR, or bring up a database.

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
