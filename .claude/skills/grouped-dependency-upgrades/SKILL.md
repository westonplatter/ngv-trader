---
name: grouped-dependency-upgrades
description: Batch many small bot dependency PRs into a few reviewable ones, across any ecosystem (bun/npm, uv/pip, cargo, go, github-actions), and resolve transitive vulnerabilities no bot PR can reach. Use when the user asks to "batch the dependabot PRs", "group the dependency updates", "clean up the bumps", "handle the renovate PRs", "run the audit", or "fix the CVEs", or when several `chore(deps)` PRs are open at once. Covers triage by risk tier, the supply-chain cooldown, baseline-diff verification, and closing superseded PRs.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
---

# Grouped Dependency Upgrades

Dependabot and renovate open one PR per package. A repo with two ecosystems
easily carries a dozen open bumps, each burning a CI run and a review. This
skill batches the safe ones into a few PRs, keeps the risky ones separate, and
handles the transitive CVEs that no bot PR can fix.

Everything ecosystem-specific lives in `adapters/*.json`. The policy below is
the same for JavaScript, Python, Rust, Go, or anything else with a lockfile.

Commands below assume this shorthand — the repo root has its own `scripts/`, so the
path must be explicit:

```bash
SKILL=.claude/skills/grouped-dependency-upgrades
$SKILL/scripts/compare_baseline.py --list      # adapters this repo has
```

New to this workflow? [references/workflow.md](references/workflow.md) draws it, and
[references/running-locally.md](references/running-locally.md) is the by-hand runbook.

## Step 0 — learn the repo's conventions

Read, if present: `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`. They own commit
format, PR body sections, cooldown policy, and issue tracking. Do not restate
or override them from here. Repo-specific facts (which checks are already red,
which tracker to file in) belong in `references/repo-<name>.md`.

## Risk tiers

| Tier       | Shape                                                                                     | Handling                                        |
| ---------- | ----------------------------------------------------------------------------------------- | ----------------------------------------------- |
| **Low**    | Patch on `>=1.0`; type stubs; dev-only minors                                              | Group into one PR per ecosystem                 |
| **Medium** | Runtime minors; **any `0.x` minor**; type-stub majors; requirement widenings; bumps to the tools that produce your baseline numbers | Group into a **second** PR per ecosystem, verified separately |
| **High**   | Any major; anything in the adapter's `toolchain` list                                      | Out of scope — leave the individual PR open     |

`0.x` minor bumps are **medium, not low** — semver lets `0.4 → 0.5` break
freely, and whole ecosystems (Python especially) live at `0.x` permanently.

Two tiers means at most two PRs per ecosystem. **Never mix tiers, and never mix
ecosystems, in one branch**: separate lockfiles, separate CI signal, separate
revert blast radius. A medium-tier regression must be bisectable without
reverting six safe bumps.

Full rules and a worked example: [references/triage.md](references/triage.md).

## Procedure

### 1. Triage

```bash
$SKILL/scripts/triage_prs.py --repo <owner>/<name>
```

No `gh` on PATH (web and mobile sessions have none)? Fetch the PRs with the
GitHub MCP tool `list_pull_requests` (fields `number,title,user,labels,head`),
save the JSON, and pass `--from-file <path>`. State the split to the user
before touching anything.

### 2. Record the baseline — before changing anything

Most repos do not gate every check in CI, so some checks are already failing on
the base branch. **A passing check is not the bar; an unchanged check is.**

```bash
$SKILL/scripts/compare_baseline.py --adapter <id>
```

Run it once with a clean tree to capture the baseline, then again after the
bumps to diff. It uses a detached git worktree, never the stash — see
[Pitfalls](#pitfalls). Adapters with no local metrics (e.g. `github-actions`)
say so and defer to the PR's own CI run.

### 3. Branch and bump

```bash
git fetch origin main && git checkout -b chore/deps-<ecosystem>-<tier> origin/main
```

Then run the adapter's `add` command for each package, and apply its
`post_add_fixup` — most package managers rewrite the manifest in ways you did
not ask for (pinning exact where a range was intended, writing a dev tool into
the runtime section, widening a floor). Diff the manifest and confirm only the
version changed.

**Then check the blast radius**, with the adapter's `lock_delta_cmd`:

```bash
git diff <lockfile> | grep -c '<version marker>'   # should equal the packages you bumped
```

A bump command can quietly re-resolve the whole graph instead of moving one
package — measured here, one wrong flag turned a single dev patch bump into 94
moved packages. If the count exceeds what you bumped, reset the lock and use
the adapter's surgical form; do not ship the extra upgrades inside a low-tier
PR, where nobody is reviewing them.

**An overshoot is not automatically a re-resolve.** A package released in
lockstep with siblings brings them along legitimately — `ai` 7.0.52 → 7.0.62
moved 7 lock entries: itself, one other direct bump, and four `@ai-sdk/*`
internals it depends on. Name every extra entry and decide, rather than
resetting on the count alone. What distinguishes the two: a re-resolve moves
packages unrelated to anything you named. Run the extras through
`check_cooldown.py` as well — they were never in a bot PR, so nothing else
checked their publish dates.

### 4. Verify against the baseline

Re-run `compare_baseline.py --adapter <id>`. Every metric must be **identical
to baseline** or better; the script exits 1 otherwise. A lockfile that shrinks
is normal — a bump often drops transitive deps. Read the lock diff and be able
to explain any removals in the PR body.

**Exception:** if the batch bumps a package in the adapter's `baseline_tools`
(the linter, the type checker, the test runner), it moved its own yardstick. An
unchanged count is no longer evidence — read the new findings themselves. This
is not hypothetical: an `eslint-plugin-react-hooks` 7.0.1 → 7.1.1 patch in this
repo took the lint count from 6 to 13 with no source change.

**A metric can also come back `UNMEASURABLE`** — the command failed and printed
nothing the pattern recognizes (a suite that never reached a test body, a
linter that died on its config). That is not a pass. Fix the environment or
drop the metric explicitly with `--metrics`, and say which checks did not run
in the PR.

### 5. Audit

Run the adapter's `audit_cmd` if it has one. Handle findings per
[Transitive vulnerabilities](#transitive-vulnerabilities), and always report
the before/after count. Where an ecosystem has no audit command, say so rather
than implying it was checked.

### 6. Ship

Commit and open the PR per the repo's conventions, listing every package and
its from→to in the body. **State explicitly that the checks match the base
branch baseline, with the numbers** — reviewers otherwise read a red check as
this PR's fault.

### 7. Close the superseded PRs

Merging does **not** close them:

- `supersedes #164` is not a closing keyword. Only `closes`/`fixes`/`resolves`
  auto-close, and only for _issues_ — never for other PRs.
- Dependabot does eventually close its own superseded PRs, but only on its next
  scheduled run — up to a week with `interval: "weekly"`.

**Comment on each superseded PR as soon as the grouped PR opens** — not at
merge. Between opening and merging, those PRs are still in the queue and still
look live; a reviewer or a later agent will otherwise re-do work that is
already done. One comment per superseded PR, naming the grouped PR number, the
verification it passed, and that this one stays open until the grouped PR
merges. Cross-reference the other direction too: list every superseded number
in the grouped PR body.

```bash
gh pr comment <n> --body "Superseded by #<grouped>, which carries this bump
alongside the other <tier> <ecosystem> updates in one reviewable PR. Verified
there against the base-branch baseline (<numbers>) and past the cooldown.

Leaving this open until #<grouped> merges; it will be closed then."
```

Then close them explicitly once the grouped PR merges: `gh pr close <n>
--comment "Merged as part of #<grouped>."`. Without `gh` (web and mobile
sessions), the same two steps are the MCP `add_issue_comment` and
`update_pull_request` with `state: "closed"`.

## Cooldown

New releases are the supply-chain risk window. Check every version before it
lands, including transitive pins:

```bash
$SKILL/scripts/check_cooldown.py --adapter <id> <pkg>@<version> ...
```

It reads the actual publish date from npm, PyPI, crates.io, the Go module
proxy, or RubyGems, and exits 1 inside the window. Each adapter records whether
its cooldown is **mechanical** (the installer refuses, e.g. bun's
`minimumReleaseAge`) or **manual** (a flag someone has to remember, e.g.
`uv add --exclude-newer`). Manual ones are why this script exists.

A refused install is the policy working. Do not add an exclusion to get around
it — leave the bump for next week.

## Transitive vulnerabilities

Audit findings usually sit in packages with **no direct entry** in the
manifest. No bot PR can fix these — they are blocked until each parent ships a
release. Force them with the adapter's `transitive_pin` mechanism (npm
`overrides`, uv `constraint-dependencies`, cargo `[patch]`, go `replace`).

1. **Check the cooldown per pin.** A pin bypasses the installer's own check, so
   nothing stops you pinning a package published yesterday. Inside the window →
   leave the finding open and say so in the PR.
2. **Ship pins as their own PR**, never folded into a version-bump PR.
3. **Prove the toolchain survived.** Forcing a package that sits under the
   linter or bundler is exactly what silently breaks them. Unchanged baseline
   counts are the evidence that both still execute — cite them.
4. **Justify each entry in the commit body**, with the advisory and the path.
   Drop each pin once its parent resolves it naturally.

Leave low-severity dev-only findings alone unless the user asks.

## Pitfalls

- **Never use `git stash` to capture a baseline.** With a clean tree `git stash`
  saves nothing, and a later `git stash pop` then applies an unrelated stale
  stash — silently dumping months-old work, conflict markers and all, into the
  tree. Use `compare_baseline.py` (git worktree) instead.
- **Check for a dirty tree before branching.** Other agents may be mid-edit.
  `git status --porcelain` first; stage only the files you touched, by path.
- **A baseline worktree is a clean checkout.** Gitignored config the checks
  need (env files, local settings) is absent, so the baseline fails for the
  wrong reason. Declare those in the adapter's `link_untracked`.
- **Do not chase the pre-existing failures.** Fixing them is a separate PR;
  burying it inside a dep bump makes both unreviewable.
- **A routine-looking bump can be a security fix.** Patch releases quietly
  carry high-severity advisories. Audit before *and* after; call out anything
  material in the PR.
- **Verify one bump you did not choose.** Bot PRs sometimes bump a package the
  manifest pins deliberately. Read the manifest diff, not just the lock.

## Adding an ecosystem

Copy `adapters/_template.json`, fill it in, and write a matching
`references/<id>.md` for the caveats you hit. See
[references/adding-an-ecosystem.md](references/adding-an-ecosystem.md). Nothing
in this file should need to change.
