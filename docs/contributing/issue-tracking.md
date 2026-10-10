---
topics: ["issues", "beads", "workflow"]
description: Optional issue tracking with beads (the bd CLI) — creating issues, working the queue, and the conventions for claiming, noting, and closing.
---

# Issue Tracking

Issue tracking is **optional**. The maintainer uses
[beads](https://beads.gascity.com/getting-started/quickstart) — a dependency-aware
ledger stored in an embedded Dolt database under `.beads/` and driven by the `bd`
CLI — but nothing in the repo requires it. If `bd` finds no `.beads/` directory
walking up from the cwd, skip this page.

Ids are hash-based and prefixed with the repo (e.g. `ngv-trader-xms`), not numbers.
There is no project flag: `bd` locates `.beads/` by walking up from the cwd.

One rule when you do use it: **closing asserts the work is complete.** If it isn't,
leave the issue open and `bd note <id> "what remains"`.

## Adding an issue

```bash
bd create "Add 3 Days trade sync button to Trades page" \
  -t feature -p 2 -l "frontend,trades" \
  -d "What changes and where, with file paths." \
  --acceptance "Observable done condition."
```

- `-t` type: `task` (default), `bug`, `feature`, `chore`, `epic`, `decision`, `spike`, `story`. `bd types` lists them.
- `-p` priority: `0`–`4`, 0 highest, default `2`.
- `-l` labels: comma-separated.
- `--parent <id>` files a child under an epic; `--deps 'blocks:<id>'` (or `bd dep add <id> <blocker>`) records a blocker.
- `--silent` prints only the new id — use it when scripting. `--dry-run` previews.

Search before creating: `bd search "trade sync"`, `bd find-duplicates`.

## Working the queue

```bash
bd ready                                  # open issues with no active blockers
bd list --status open
bd show ngv-trader-xms
bd update ngv-trader-xms --claim          # assign to self + in_progress
bd note ngv-trader-xms "approach notes"
bd close ngv-trader-xms --reason "Shipped in PR #199; verified with bunx tsc --noEmit"
```

## Conventions

- Write descriptions a fresh agent can act on: file paths, the observable behavior, acceptance criteria.
- Add `--json` to any command when piping to `jq`; plain output otherwise.
- `bd prime` prints the full agent workflow contract; `bd quickstart` is the short version.
- Sync is Dolt-native (`bd dolt push` / `bd dolt pull`). Git hooks are not installed in this clone — `bd hooks install` to opt in.
