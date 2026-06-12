# Doc Review Process

Checklist and conventions for reviewing and refining project documentation.

## Scope

Review covers: `README.md`, `AGENTS.md`, and all files in `docs/`. Goal is to keep docs accurate, complete, and consistent with the actual codebase — not to expand or restructure them.

## Steps

### 1. Read every doc file

Read all files in scope before making any changes. Build a mental model of what each file claims before cross-checking.

### 2. Cross-check against the codebase

For each doc, verify the following against actual code:

| Check | How |
| --- | --- |
| **Routes** | For each router file referenced, extract every `@router.{method}(path)` decorator and compare to the endpoint list in the doc. |
| **Table names / columns** | Spot-check against `src/models.py` and `alembic/versions/`. |
| **Scripts** | Verify each script path in `scripts/` exists with `ls scripts/`. |
| **Key files sections** | For every "Key files" table or list in any doc, verify each path exists on disk. |
| **Internal links** | Grep all `[text](relative/path)` references across every doc; confirm each target file exists. |
| **Env vars** | Check that example values and var names match `.env.example`. |
| **Spec status banners** | Confirm each `spec-*.md` has a status banner at the top and its `_index.md` entry reflects current status. |
| **Task commands** | Verify each `task <name>` command exists in `Taskfile.yaml` with the documented behavior. |

### 3. Distinguish doc gaps from code gaps

- **Doc gap** — the code is correct but the doc is stale, incomplete, or wrong.
- **Code gap** — the doc reveals something that should exist in the codebase but doesn't (e.g., a file that components import from but isn't on disk).

Fix doc gaps in this PR. Flag code gaps in the PR description under a **Code gaps found** section so they get separate follow-up. Do not attempt to fix code gaps in a doc review pass.

### 4. Compile a priority table

Before editing anything, compile findings into a table:

| Priority | File | Change |
| --- | --- | --- |
| High | `file.md` | Short description: what's wrong and what the fix is |
| Medium | `docs/file.md` | ... |
| Low | `docs/file.md` | ... |

Priority guide:

- **High** — incorrect or missing information that actively misleads a developer (wrong commands, missing routes, stale architecture description).
- **Medium** — broken references, outdated details, contradictions between files.
- **Low** — minor inconsistencies, style issues, nice-to-have clarifications.

### 5. Make changes

Edit only what is in the priority table. Do not expand scope, refactor structure, or clean up style beyond what was flagged.

After any change to a doc file, verify `docs/_index.md` is still accurate per the rule in `AGENTS.md`.

### 6. Commit and open a PR

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
