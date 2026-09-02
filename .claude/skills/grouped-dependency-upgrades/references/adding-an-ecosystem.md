# Adding an ecosystem

Copy `adapters/_template.json` to `adapters/<id>.json` and fill it in. The
skill body does not change.

## Fields

| Field | Purpose |
| --- | --- |
| `id`, `dir` | Adapter name; directory the commands run in, relative to the repo root. |
| `dependabot_ecosystems`, `labels` | How triage maps a PR to this adapter (branch segment, PR labels). |
| `registry` | `npm` \| `pypi` \| `crates` \| `go` \| `rubygems` — used by `check_cooldown.py`. |
| `install` | Command to materialize dependencies before measuring. |
| `add`, `post_add_fixup` | How to apply a bump, and what the tool rewrites behind your back. |
| `add_lock_only` | Surgical form for a lock-only move, where the ecosystem has one. |
| `lock_delta_cmd` | Prints how many packages' versions moved — catches a bump that re-resolved the whole graph. |
| `cooldown` | `days`, and `mode`: `mechanical` (installer refuses), `manual` (a flag someone must remember), `dependabot` (config-side only). |
| `audit_cmd` | Vulnerability scan, or `null` if the ecosystem has none locally. |
| `transitive_pin` | File and field that force a transitive version. |
| `toolchain` | Packages that decide whether the repo builds — non-patch bumps are high tier. |
| `baseline_tools` | Packages that **produce** the metrics; bumping one invalidates count-comparison. |
| `types_prefixes` | Type-stub package prefixes (`@types/`, `types-`). |
| `link_untracked` | Gitignored files the checks need, copied into the baseline worktree. |
| `metrics` | The health checks. See below. |

## Metrics

Each metric reduces one command's output to a single lower-is-better integer:

- `mode: "count"` — number of lines matching `pattern` (e.g. `error TS`).
- `mode: "capture"` — first capture group of the first match, as an int
  (e.g. `Found ([0-9]+) error`).
- `mode: "status"` — 0 if the command exits 0, else 1.

A `count`/`capture` metric whose command **fails and matches nothing** reports
`UNMEASURABLE`, not 0 — 0 on both sides would read as "same" for a check that
never ran.

Pick commands a contributor already runs locally, and verify the pattern
against real output — including *failing* output — before trusting it. Two real
misfires from this repo: an unanchored `([0-9]+) failed` matched
`port 5432 failed: Connection refused` and reported `5432` test failures; a bare
`([0-9]+) error` can match a lint finding's own message text instead of the
summary. Anchor on the tool's summary line.

## Known mappings

| Ecosystem | install | add | audit | transitive pin | registry |
| --- | --- | --- | --- | --- | --- |
| bun / npm | `bun install` | `bun add p@v` | `bun audit` | `overrides` | npm |
| uv / pip | `uv sync` | `uv add 'p==v'` | none built in | `[tool.uv] constraint-dependencies` | pypi |
| cargo | `cargo fetch` | `cargo update -p p --precise v` | `cargo audit` | `cargo update -p c --precise v`, else an exact `[dependencies]` pin | crates |
| go | `go mod download` | `go get p@v` | `govulncheck ./...` | `replace` | go |
| bundler | `bundle install` | `bundle update p` | `bundle audit` | — | rubygems |
| github-actions | — | edit the workflow pin | — | — | — |

`[patch.crates-io]` is **not** a transitive pin: cargo requires a patch to
point at a different source (git or path), so it cannot force another version
already published on crates.io.

Only adapters validated against this repo ship here. Add one when you have run
its metrics and seen real numbers — an unvalidated adapter is worse than none,
because its zeros look like success.
