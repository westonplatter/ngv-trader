---
name: ngv-frontend-grouped-upgrades
description: Group low- and medium-complexity frontend dependency updates into a single reviewable PR, and resolve transitive vulnerabilities that dependabot cannot reach. Use when the user asks to "batch the dependabot PRs", "group the JS updates", "clean up the frontend bumps", "run bun audit", "fix the frontend CVEs", or when several `chore(deps)` PRs against `/frontend` are open at once. Covers triage by risk tier, the 14-day supply-chain cooldown, baseline-diff verification, and closing superseded dependabot PRs.
allowed-tools: Read, Grep, Glob, Bash, Edit, Write
---

# NGV Frontend Grouped Upgrades

Dependabot opens one PR per package. For `frontend/` that means six-plus PRs of
patch bumps, each burning a CI run and a review. This skill batches the safe ones
into a single PR, keeps the risky ones separate, and handles the transitive CVEs
that no dependabot PR can fix.

**Read `AGENTS.md` first** — commit format, PR body sections, and the cooldown
policy live there and are not restated here.

## Risk tiers

Triage every open `chore(deps*)` PR against `/frontend` before touching anything.

| Tier       | Shape                                                                                       | Handling                                               |
| ---------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| **Low**    | Patch/minor on `>=1.0` packages; `@types/*` bumps                                           | Group into one PR                                      |
| **Medium** | Minor bumps with real runtime surface (charting, routing, data fetching); `0.x` minor bumps | Group into a **second** PR, verified separately        |
| **High**   | Any major; anything touching the build (`vite`, `typescript`, `eslint` majors)              | Out of scope — leave the individual dependabot PR open |

`0.x` minor bumps are **medium, not low** — semver lets `0.4 → 0.5` break freely.
Python bumps (`uv` ecosystem) are always out of scope here.

Two tiers means at most two PRs. Never mix tiers in one branch: the whole point
is that a medium-tier regression is bisectable without reverting six safe bumps.

## Procedure

### 1. Triage

```bash
gh pr list --limit 50 --json number,title,author --jq \
  '.[] | select(.author.login=="app/dependabot") | "\(.number)  \(.title)"'
```

Sort into the tiers above. State the split to the user before proceeding.

### 2. Record the baseline — before changing anything

**`main` is currently red.** The frontend build and lint are not gated in CI
(`.github/workflows/tests.yml` runs pytest only), so `tsc -b` and `eslint` carry
pre-existing failures. A passing check is not the bar; an **unchanged** check is.

```bash
.claude/skills/ngv-frontend-grouped-upgrades/scripts/compare-baseline.sh
```

Run it once with a clean tree to capture the baseline, then again after the
bumps to diff. It uses a detached git worktree, never the stash — see
[Pitfalls](#pitfalls).

### 3. Branch and bump

```bash
git fetch origin main && git checkout -b chore/group-low-risk-js-deps origin/main
cd frontend && bun add <pkg>@<version> ...
```

`bun add` writes an **exact** version (`"7.0.41"`), discarding the caret range.
Restore the ranges so the manifest keeps its original intent:

```bash
# after bun add, revert "pkg": "1.2.3" back to "pkg": "^1.2.3", then:
bun install
```

`bun add` does preserve the dep/devDep section correctly — only the range needs
fixing. Verify with `git diff frontend/package.json` that nothing moved sections.

The 14-day cooldown is enforced mechanically by `minimumReleaseAge` in
`frontend/bunfig.toml`; if `bun add` refuses a version, that is the policy
working. Do not add a `minimumReleaseAgeExcludes` entry to get around it.

### 4. Verify against the baseline

Re-run `compare-baseline.sh`. Every metric must be **identical to baseline** or
better. A lockfile that shrinks is normal — a bump often drops transitive deps.
Read the `bun.lock` diff and be able to explain any removals in the PR body.

### 5. Audit

```bash
cd frontend && bun audit
```

Handle findings per [Transitive vulnerabilities](#transitive-vulnerabilities).
Always report the before/after count.

### 6. Ship

Commit per `AGENTS.md` (`chore(deps): ...`), listing every package and its
from→to in the body. Open the PR with the full write-up `AGENTS.md` requires.

In the PR body, state explicitly that build/lint counts match the `main`
baseline — reviewers otherwise read a red check as this PR's fault.

### 7. Close the superseded PRs

Merging does **not** close them:

- `supersedes #164` is not a closing keyword. Only `closes`/`fixes`/`resolves`
  auto-close, and only for _issues_ — never for other PRs.
- Dependabot does eventually close its own superseded PRs, but only on its next
  scheduled run. `.github/dependabot.yml` sets `interval: "weekly"`, so they
  linger up to ~7 days.

Close them explicitly once the grouped PR merges:

```bash
for n in <numbers>; do
  gh pr close $n --comment "Superseded by #<grouped>, which grouped this bump with other low-risk frontend updates into a single change. The version here is already on \`main\`."
done
```

## Transitive vulnerabilities

`bun audit` findings usually sit in packages with **no direct entry** in
`package.json` (`brace-expansion` under `eslint`, `picomatch` under `vite`,
`protocol-buffers-schema` under `plotly.js`). Dependabot cannot fix these — they
are blocked until each parent ships a release. Force them with `overrides`:

```jsonc
// frontend/package.json
"overrides": {
  "brace-expansion": "^5.0.9",
  "picomatch": "^4.0.5"
}
```

Rules for overrides:

1. **Check the cooldown per pin.** An override bypasses `bun add`, so nothing
   stops you pinning a package published yesterday. Verify each one:
   ```bash
   bun pm view <pkg>@<version> | grep -i published
   ```
   Inside 14 days → leave the finding open and say so in the PR. Do not exclude.
2. **Ship overrides as their own PR**, never folded into a version-bump PR.
3. **Prove the toolchain survived.** Forcing `minimatch`/`picomatch` under
   `eslint` and `typescript-eslint` is exactly what silently breaks linting.
   Unchanged `bun run lint` and `bun run build` counts are the evidence that
   both still execute — cite them.
4. **Justify each entry in the commit body**, with the advisory and the path.
   Each pin should be dropped once its parent resolves it naturally.

Leave low-severity dev-only findings alone unless the user asks.

## Pitfalls

- **Never use `git stash` to capture a baseline.** With a clean tree `git stash`
  saves nothing, and a later `git stash pop` then applies an unrelated stale
  stash — silently dumping months-old work, conflict markers and all, into the
  tree. Use `compare-baseline.sh` (git worktree) instead.
- **Check for a dirty tree before branching.** Other agents may be mid-edit.
  `git status --porcelain` first; stage only the files you touched, by path.
- **A green `bun run typecheck` does not mean the build is clean.** `typecheck`
  runs `tsc --noEmit` against the solution config and passes trivially; `build`
  runs `tsc -b`, which actually resolves the referenced projects. Always run
  `build`.
- **Don't chase the baseline failures.** The 18 `tsc -b` errors are demo
  fixtures in `src/lib/demoData.ts` drifted from the `Position`/`TradeGroup`
  types. Fixing them is a separate PR, and burying it inside a dep bump makes
  both unreviewable.
- **A routine-looking bump can be a security fix.** `react-router-dom` 7.18.2
  patched a high-severity CSRF advisory while reading as an ordinary patch.
  Audit before _and_ after; call out anything material in the PR.

## Tracking

Track the batch in kata (`--project ngv-tradrer`, see `AGENTS.md`). One issue per
batch, listing the grouped PR numbers and the ones deliberately left out. Close
it only after the grouped PR merges and the superseded PRs are closed.
