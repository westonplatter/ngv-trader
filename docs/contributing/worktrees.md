---
topics: ["git", "worktrees", "agents", "workflow"]
code_dirs_or_files:
  [
    ".worktreeinclude",
    ".claude/hooks/session-start.sh",
    "src/utils/worktree.py",
    "scripts/worktree_test_db.py",
    "tests/conftest.py",
    "Taskfile.yaml",
  ]
description: Running several agents at once with git worktrees — one run seat, many edit seats, what each may touch, and the setup and cleanup steps.
---

# Worktrees

Run several agents on the repo at once, each in its own git worktree, and open any
of them in Cursor or vim. Git isolates files per worktree and nothing else: ports,
databases, and the job queue exist once per machine.

## Who can touch what

```text
      one repository: a commit made in any seat is visible in all of them
             ┌────────────────────────────┬───────────────────────────┐
             │                            │                           │
┌────────────┴─────────────┐  ┌───────────┴────────────┐  ┌───────────┴────────────┐
│ RUN SEAT · you           │  │ EDIT SEAT · agent A    │  │ EDIT SEAT · agent B    │
│ ngv-trader/  (main)      │  │ .claude/worktrees/     │  │ .claude/worktrees/     │
│ holds the real .git/     │  │   fix-roll/            │  │   vol-surf/            │
│                          │  │ worktree-fix-roll      │  │ worktree-vol-surf      │
│ task api       :8000     │  │                        │  │                        │
│ task frontend  :5173     │  │ scripts/check.py       │  │ scripts/check.py       │
│ task worker:jobs         │  │ ruff · pyright         │  │ ruff · pyright         │
│ task worker:orders       │  │ task test              │  │ task test              │
│ task migrate ENV=dev     │  │ bun typecheck/lint/test│  │ bun typecheck/lint/test│
└──┬─────────┬─────────┬───┘  └─────────────────────┬──┘  └────────────┬───────────┘
   │ serves  │ migrates│ runs     ✗ never: workers, │ task             │ task test
   │         │         │ workers    dev migrations  │ test             │
   ▼         ▼         ▼                            ▼                  ▼
┌──────┐ ┌───────┐ ┌───────┐  ┌────────────────────────┐  ┌────────────────────────┐
│ Ports│ │ Dev DB│ │ Job   │  │ its own test DB        │  │ its own test DB        │
│ 8000 │ │       │ │ queue │  │ ngv_trader_            │  │ ngv_trader_            │
│ 5173 │ │       │ │ + TWS │  │   fix_roll_test        │  │   vol_surf_test        │
└──────┘ └───────┘ └───────┘  └────────────────────────┘  └────────────────────────┘
shared by the whole machine                     one per worktree
```

- **Run seat.** The main checkout is the only place the stack runs.
- **Edit seat.** A worktree edits, commits, and runs the checks that need no ports.
- **The `✗` note** is drawn under agent A and applies to every worktree.

## Life of one task

1. **Start.** `claude --worktree fix-roll` creates `.claude/worktrees/fix-roll/` on a
   new branch `worktree-fix-roll` from `origin/main`. Repeat in another terminal for
   a second agent.
2. **Bootstrap (automatic).** Claude Code copies the files in `.worktreeinclude`
   (`.env.dev`, `.envrc`). The SessionStart hook installs deps when the worktree has
   none. Outside Claude Code, run `task wt:setup` in the worktree.
3. **Work.** The agent edits, commits, and runs checks. `task test` uses the
   worktree's own test database with no configuration.
4. **Review.** Open the folder: `cursor .claude/worktrees/fix-roll`, or `:tcd` to it
   in vim. To see it run, detach the main checkout onto the branch and the running
   stack reloads: `git switch --detach worktree-fix-roll`. That shows committed work
   only; `git switch -` returns.
5. **Ship.** Push the branch; one branch, one PR.
6. **Clean up.** Run `task wt:clean` in the worktree to drop its test database, then
   exit the session. Claude Code removes a clean worktree and asks before removing
   one that still holds work. By hand: `git worktree remove <path>`.

## Rules

| Shared thing      | What goes wrong                                                   | Rule                                                                           |
| ----------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Test database     | Two suites at once overwrite each other's data and schema         | Automatic: each worktree gets its own                                          |
| Dev database      | A branch's migration leaves it at a revision other branches lack  | Worktrees write migrations; only the run seat runs `task migrate ENV=dev`      |
| Alembic heads     | Two branches each add a migration: two heads after merge          | The second branch to merge rebases and re-points `down_revision`               |
| Job queue and TWS | A feature-branch worker would execute real jobs and orders        | Workers run only from the run seat                                             |
| Ports 8000 / 5173 | Hardcoded, with one CORS origin; a second stack can't start clean | One running stack                                                              |
| Prod connection   | `task` defaults to `ENV=prod`                                     | `.env.prod` is not copied into worktrees; do not add it to `.worktreeinclude`  |

## Test database per worktree

`src/utils/worktree.py` names it. In the main checkout, and in CI, the suite uses
`ngv_trader_test`. In a linked worktree (its `.git` is a file, not a directory) it
uses `ngv_trader_<directory>_test`, created and migrated on demand like the shared
one. `TEST_DB_NAME` still overrides both.

- Show the name: `uv run python scripts/worktree_test_db.py name`
- Drop it: `task wt:clean` (refuses the shared `ngv_trader_test`)

## Other tools

Worktrees made by Cursor, Codex, or `git worktree add` work the same way: the test
database naming is automatic, and `task wt:setup` replaces the hook. Only the
`.worktreeinclude` copy is specific to Claude Code; copy `.env.dev` by hand
elsewhere.
