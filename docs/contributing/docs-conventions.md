---
topics: ["docs", "conventions", "specs"]
code_dirs_or_files: ["scripts/docs_index.py", "scripts/docs_check.py", "docs/"]
description: How docs are organized and maintained — generated indexes, spec status banners and the ship-time wrap-up, front matter, and the writing style for docs and summaries.
---

# Docs Conventions

The ongoing review process (same-change rule, drift fixes, weekly pass) is in
[doc-review.md](../doc-review.md). This page covers the structural rules.

## Generated indexes

Doc indexes are generated. If any `docs/**/*.md` file is added, renamed, or deleted
(or its front-matter `description`/`topics` changes), regenerate the indexes in the
same change:

```bash
uv run python scripts/docs_index.py
```

This writes a `README.md` into `docs/` and every docs subdirectory that contains
`.md` files (GitHub auto-renders these), `docs/core/` included. Index files are
generated artifacts — never edit them by hand.

## Front matter

Optional, but it feeds the indexes:

```yaml
---
topics: ["trades", "sync"]
code_dirs_or_files: ["src/services/trade_sync_flexquery.py"]
description: One sentence that tells a reader whether to open this doc.
---
```

Docs without front matter are still listed. `code_dirs_or_files` doubles as the
churn signal for the weekly review pass.

## Specs

Every `spec-*.md` carries a status banner at the top (e.g. `Status: NOT IMPLEMENTED`
/ `PARTIAL`). Specs are planning artifacts: change only the banner as state moves.

When a spec ships, do the wrap-up in the same change:

1. Rewrite it to describe the system as it works today, or fold it into the relevant current-state doc.
2. If kept as a standalone file, remove the `spec-` prefix; if folded, delete the spec file.
3. Update any in-repo references to the old filename.
4. Regenerate the indexes.

## Plans

`docs/plans/` holds dated planning artifacts. They are historical: the doc checker
exempts them from script-path checks, and they must never pin an account to real
activity (see [ibkr-sample-data.md](../ibkr-sample-data.md#account-references-in-committed-content)).

## Writing style

Compact, high signal-to-noise, written for an engineer-to-engineer dialogue.

- Default to high-level overviews that point to detailed resources rather than verbose step-by-step instructions.
- Avoid hardcoding filenames when the reader wants lightweight guidance.
- Prefer short sentences and direct statements; cut filler and marketing.
- Use plain language and concrete terms.
- Keep sections small; remove anything nonessential.
- Use bullets for quick scanning; avoid long paragraphs.
- Favor commands and examples over prose.
- State assumptions explicitly when needed.
- Avoid redundancy.

## After any doc change

```bash
uv run python scripts/docs_check.py
```

Details in [validation.md](validation.md#doc-checks).
