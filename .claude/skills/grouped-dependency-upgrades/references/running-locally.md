# Running it locally

Ask Claude Code to "batch the dependabot PRs" and the skill drives this itself.
These are the same steps run by hand.

**Prerequisites:** `bun`, `uv`, and a git remote you can fetch. `gh` is optional
(see [Without `gh`](#without-gh)). Registry lookups need network. Postgres is
needed only for the Python `tests` metric.

```bash
SKILL=.claude/skills/grouped-dependency-upgrades   # all commands run from the repo root
```

## 1. See the queue (both ecosystems at once)

```bash
$SKILL/scripts/triage_prs.py --repo westonplatter/ngv-trader
```

Prints every open bot PR grouped by ecosystem and tier, with the branch name to
use. Nothing is written. Majors and toolchain bumps are listed as HIGH — leave
those PRs alone.

## 2. Record the baseline — before touching anything

This must run on a **clean tree**, or the "before" number already contains your
change.

```bash
$SKILL/scripts/compare_baseline.py --adapter bun    # ~3 min
$SKILL/scripts/compare_baseline.py --adapter uv     # ~2 min, needs Postgres for `tests`
```

No database running? Drop that metric explicitly rather than letting it report
a meaningless number:

```bash
$SKILL/scripts/compare_baseline.py --adapter uv --metrics imports,lint
```

On a clean tree both columns should read identical and every verdict `same` —
that is the run confirming your starting point, and those are the numbers you
will cite in the PR. Current values on `origin/main`: bun 17 build / 13 lint /
2 audit, uv 0 imports / 76 lint.

## 3. Branch, one tier and one ecosystem at a time

```bash
git fetch origin main && git checkout -b chore/deps-bun-low origin/main
```

## 4. Bump

**JavaScript** — `bun add` strips the caret and pins exact, so put the range
back:

```bash
cd frontend
bun add ai@7.0.52 @types/react-dom@19.2.4
# edit package.json: "7.0.52" -> "^7.0.52" for each package
bun install && cd ..
```

The 14-day cooldown is mechanical here — if `bun add` refuses a version, that
is the policy working. Do not add a `minimumReleaseAgeExcludes` entry.

**Python** — the command depends on where the package lives:

```bash
uv add --group dev 'ruff==0.16.1'              # dev-group tool
uv add 'alembic==1.19.0'                       # runtime dependency
uv lock --upgrade-package fastapi==0.141.1     # lock-only, manifest floor already fits
```

**Never add `--exclude-newer` to a bump.** On an existing lock it re-resolves
the whole graph — measured at 94 moved packages for one dev patch bump. Omitting
`--group dev` is the other trap: uv files the dev tool as a runtime dependency.

## 5. Check the blast radius and the cooldown

The lock should move exactly the packages you bumped:

```bash
git diff frontend/bun.lock | grep -cE '^\+ +"[^"]+": \["'    # JS
git diff uv.lock | grep -c '^+version = '                    # Python
```

More than that means the tool re-resolved: reset the lock and use the surgical
form. Then confirm every version is past the cooldown — mandatory for Python
and for any `overrides` pin, since neither is checked at install time:

```bash
$SKILL/scripts/check_cooldown.py --adapter uv 'ruff==0.16.1' 'alembic==1.19.0'
$SKILL/scripts/check_cooldown.py --adapter bun ai@7.0.52
```

## 6. Verify against the baseline

```bash
$SKILL/scripts/compare_baseline.py --adapter bun
```

Every metric must read `same` or `BETTER`; the script exits 1 on any `WORSE`.
Two results that are **not** a pass:

- `UNMEASURABLE` — the command failed and printed nothing parseable (no
  database, a broken config). Fix it or drop the metric with `--metrics`, and
  say which checks did not run.
- Counts that moved when you bumped a linter or type checker — those tools
  produce the numbers, so read the findings diff instead. An
  `eslint-plugin-react-hooks` patch moved lint 6 → 13 here with no source
  change.

## 7. Audit, ship, close

```bash
cd frontend && bun audit        # Python has no local audit command
```

Commit per AGENTS.md, cite the baseline numbers in the PR body, and after merge
close the superseded PRs by hand — `supersedes #164` closes nothing.

## Without `gh`

Claude Code web sessions have no GitHub CLI. Fetch the PRs with the MCP tool
`list_pull_requests` (fields `number,title,user,labels,head`), save the JSON,
and feed it in:

```bash
$SKILL/scripts/triage_prs.py --from-file prs.json
```

## Try it without touching anything

```bash
$SKILL/scripts/compare_baseline.py --list                    # adapters and their metrics
$SKILL/scripts/check_cooldown.py --registry pypi 'ruff==0.16.1'
$SKILL/scripts/compare_baseline.py --adapter bun --current-only   # measure, no worktree
```
