# Triage rules

`scripts/triage_prs.py` implements this. Read `classify()` — it is a rule
table, first match wins, in the same order as below.

## Title grammars

Two shapes matter, and they mean different things:

| Title | Meaning |
| --- | --- |
| `bump <pkg> from 1.2.3 to 1.2.4` | The lock moves now. Tier it by the semver delta. |
| `update <pkg> requirement from >=0.20 to >=0.32.1` | Only the manifest **floor** widens; the lock may not move until the next resolve. Always medium — the effect shows up later, on someone else's machine. |

`chore(deps-dev)` in the title marks a dev dependency; `chore(deps)` a runtime
one. The ecosystem comes from the branch (`dependabot/<ecosystem>/...`) or the
PR labels, matched against each adapter's `dependabot_ecosystems` / `labels`.

## Tier rules, in order

1. **Requirement widening** → medium.
2. **Unparseable versions** → unknown; read the PR by hand.
3. **In the adapter's `toolchain`, beyond a patch** → high. These decide whether
   the repo builds at all.
4. **Major on a type-stub package** → medium. Compile surface only, no runtime
   behavior — but `@types/node` 24 → 26 absolutely can produce type errors.
5. **Any other major** → high. Leave the bot's PR open and handle it alone.
6. **`0.x` minor** → medium. Semver gives `0.x` no compatibility promise.
7. **Minor on a `baseline_tools` package** → medium. See below.
8. **Minor on type stubs, or a dev-only minor** → low.
9. **Any other minor** → medium (it has runtime surface).
10. **Patch** → low.

## `baseline_tools`: the bump that moves its own yardstick

Verification here is "the counts did not change." That reasoning collapses when
the bumped package is the thing producing the counts — a ruff or eslint release
that adds a rule changes the number legitimately, and a typescript release
changes what `tsc` accepts.

Adapters list these in `baseline_tools`. Triage flags them; when one is in the
batch, **read the findings diff instead of trusting the count**, and say in the
PR which check moved and why.

## Worked example

13 open dependabot PRs across two ecosystems sorted into 4 grouped PRs and 4
left alone:

```
[bun] LOW      -> chore/deps-bun-low       #180 @types/react-dom 19.2.3->19.2.4, #189 ai 7.0.41->7.0.52
[bun] MEDIUM   -> chore/deps-bun-medium    #161 @types/node 24->26 (type-stub major)
                                           #186 eslint-plugin-react-hooks 7.0->7.1 (moves the baseline)
[bun] HIGH     -> leave open               #183 @ai-sdk/react 3->4, #187 typescript 5->7 (toolchain), #191 react-plotly.js 2->4
[uv]  LOW      -> chore/deps-uv-low        #181 ruff 0.16.0->0.16.1, #182 typer 0.27.0->0.27.1
[uv]  MEDIUM   -> chore/deps-uv-medium     #160 pandera >=0.20->>=0.32.1 (widening)
                                           #184 fastapi 0.140->0.141 (0.x minor), #185 alembic 1.18->1.19 (runtime minor)
[uv]  HIGH     -> leave open               #163 mcp 1.28->2.0
```

Note what the rules catch that a human skim would not: `fastapi` reads as a
routine patch-looking bump but is a `0.x` minor; `eslint-plugin-react-hooks` is
a dev dependency that would otherwise be "obviously low" despite changing the
lint numbers the whole batch is verified against.

Release-please, changelog, and other non-dependency bot PRs are filtered out —
a bot PR is only in scope if its title parses as a bump or a widening.
