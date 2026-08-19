# Doc Review Process

## Scope

Doc upkeep covers `README.md`, `AGENTS.md`, `CONCEPTS.md`, and all files in
`docs/`. Front matter (`topics`, `description`, `code_dirs_or_files`) is in
scope wherever it exists — it feeds the generated indexes, so stale metadata is
as misleading as stale prose.

Goal is accuracy and consistency with the actual codebase — not expansion or
restructuring. Doc upkeep is an **overlay on day-to-day changes**, not a
separate periodic audit: every PR that changes behavior updates its docs in
the same change, and drift found along the way is fixed where it's noticed.

## Continuous upkeep (every PR)

Applies to any PR that changes code, schema, or UX:

- **Same-change rule.** If behavior changes, the docs that describe it change in
  the same PR. A behavior change without its doc update is an incomplete PR.
- **Regenerate indexes.** After adding, renaming, or deleting any
  `docs/**/*.md` (or changing its front matter), run
  `uv run python scripts/gen_docs_index.py` and
  `uv run python scripts/gen_core_index_html.py`, then commit the regenerated
  `README.md` files. Never hand-edit an index.
- **Run the automated checks.**

  ```bash
  uv run python scripts/doc_check.py          # links, scripts, tasks, spec banners
  uv run python scripts/doc_check.py --routes  # undocumented routes (informational)
  ```

  Fix hard failures (`FAIL`) before merging; route `WARN`s are informational.

- **Spec lifecycle.** When a spec ships, do the wrap-up per the Docs Index Rule
  in `AGENTS.md` (rewrite or fold, drop the `spec-` prefix, update references,
  regenerate indexes). Update a spec's status banner when its state changes,
  not on a schedule.

## Opportunistic drift fixes

Anyone touching a doc who notices drift elsewhere fixes it or files it — do not
leave it for "the review":

- **Doc gap** (code correct, doc stale/wrong) → fix in the current PR as a
  separate `docs:` commit.
- **Code gap** (doc describes something that should exist but doesn't) → don't
  fix code in a docs change; flag it in the PR description under
  **Code gaps found** for separate follow-up.

## Weekly consolidation pass

A short pass to catch what same-change upkeep misses. Treat it as sampling and
triage, not a full re-read:

1. Run `scripts/doc_check.py` and fix failures.
2. Select a **rotating subset** of docs (not all). Prioritize docs adjacent to
   the week's changed code, using `code_dirs_or_files` front matter as the
   churn signal, plus narrative docs (`AGENTS.md` sections, workflow docs,
   architecture summaries).
3. For each selected doc, answer two questions:
   - **References true?** Run the checks below (routes, tables, paths, vars).
   - **Story true?** Does the doc's summary of _how the system works_ still
     hold? A wrong route is obvious; a stale narrative (architecture
     direction, workflow order, "current state" prose) passes every mechanical
     check while quietly misleading. Read the doc as a new contributor would
     and ask: would any claim made here lead to a wrong decision?
4. Record findings in a priority table and fix **High** items in the same PR;
   file Medium/Low as follow-up.

**Priority tiebreaker:** when severity is ambiguous, ask _would a new
contributor make a wrong decision from this?_ If yes, it's High — regardless
of whether the drift is a command, a route, or prose.

**Reference checks** (the "references true?" half):

| Check                     | How                                                                                                                                                                              |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Routes**                | Compare the doc's endpoint list to `@router.{method}(path)` decorators in the router file. `--routes` output is the starting point.                                              |
| **Table names / columns** | Spot-check against `src/models.py` and `alembic/versions/`.                                                                                                                      |
| **Key files sections**    | Verify each listed path exists on disk.                                                                                                                                          |
| **Env vars**              | Check example values and names against `.env.example`.                                                                                                                           |
| **Spec status banners**   | Confirm each `spec-*.md` banner matches the spec's actual state.                                                                                                                 |
| **Front matter accuracy** | Does `description` still match the doc, do `topics` still fit, do `code_dirs_or_files` paths still exist? Stale metadata propagates into every generated index, machine-blessed. |

**Staleness signal:** a doc unchanged while its `code_dirs_or_files` saw heavy
churn is a front-matter-and-description review candidate even when nothing
else flags it.

**Priority guide:**

- **High** — incorrect or missing information that actively misleads (wrong commands, missing routes, stale architecture).
- **Medium** — broken references, outdated details, contradictions between files.
- **Low** — minor inconsistencies, style, nice-to-have clarifications.

| Priority | File      | Change                           |
| -------- | --------- | -------------------------------- |
| High     | `file.md` | What's wrong and what the fix is |

## Conventions

- Do not cite line numbers in docs — they drift. Reference function/method names.
- Do not rewrite a doc from scratch unless it is entirely wrong.
- Do not add new docs unless a gap was explicitly identified.
- Do not change `spec-*.md` content beyond status banners — specs are planning artifacts.
- Edit only what's flagged; no drive-by restructuring or style churn.
