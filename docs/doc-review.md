# Doc Review Process

Checklist and conventions for reviewing and refining project documentation.

## Scope

Review covers: `README.md`, `AGENTS.md`, and all files in `docs/`. Goal is to keep docs accurate, complete, and consistent with the actual codebase — not to expand or restructure them.

## Steps

### 1. Run the automated checks

Run `scripts/doc_check.py` first. It handles the mechanical verifications:

```bash
uv run python scripts/doc_check.py          # links, scripts, tasks, spec banners
uv run python scripts/doc_check.py --routes  # also show undocumented routes (informational)
```

Fix any hard failures (`FAIL`) before proceeding. Informational warnings (`WARN`, routes only) are inputs for the priority table, not blockers.

### 2. Read every doc file and cross-check

Read all files in scope. For each doc, verify the following against actual code — and record findings in a priority table as you go (see format below):

| Check                     | How                                                                                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Routes**                | For each router file referenced, compare its `@router.{method}(path)` decorators to the endpoint list in the doc. Use `--routes` output as a starting point. |
| **Table names / columns** | Spot-check against `src/models.py` and `alembic/versions/`.                                                                                                  |
| **Key files sections**    | For every "Key files" table or list in any doc, verify each path exists on disk.                                                                             |
| **Env vars**              | Check that example values and var names match `.env.example`.                                                                                                |
| **Spec status banners**   | Confirm each `spec-*.md` has a status banner at the top and its status banner reflects current status.                                                       |

**Note on line numbers:** Do not cite specific line numbers in docs. They drift on every refactor. Reference function or method names instead — they are stable and searchable.

**Priority guide** (fill the table as you read, not after):

- **High** — incorrect or missing information that actively misleads a developer (wrong commands, missing routes, stale architecture description).
- **Medium** — broken references, outdated details, contradictions between files.
- **Low** — minor inconsistencies, style issues, nice-to-have clarifications.

| Priority | File           | Change                                              |
| -------- | -------------- | --------------------------------------------------- |
| High     | `file.md`      | Short description: what's wrong and what the fix is |
| Medium   | `docs/file.md` | ...                                                 |

### 3. Distinguish doc gaps from code gaps

- **Doc gap** — the code is correct but the doc is stale, incomplete, or wrong.
- **Code gap** — the doc reveals something that should exist in the codebase but doesn't (e.g., a file that components import from but isn't on disk).

Fix doc gaps in this PR. Flag code gaps in the PR description under a **Code gaps found** section so they get separate follow-up. Do not attempt to fix code gaps in a doc review pass.

### 4. Make changes

Edit only what is in the priority table. Do not expand scope, refactor structure, or clean up style beyond what was flagged.

After adding or renaming a doc file, regenerate the indexes with `uv run python scripts/gen_docs_index.py`.

### 5. Commit and open a PR

Commit message format:

```
docs: short summary of what changed

One sentence per logical fix.
```

PR description must include:

- The same priority table under a `## Changes` heading.
- A `## Code gaps found` section if any code gaps were identified (or "None" if clean).

## What Not to Do

- Do not fix code as part of a doc review. Flag it and move on.
- Do not rewrite docs from scratch unless they are entirely wrong.
- Do not add new docs unless a gap was explicitly identified.
- Do not change content in `spec-*.md` files beyond updating status banners — specs are planning artifacts.
