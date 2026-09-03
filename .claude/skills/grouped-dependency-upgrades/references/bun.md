# bun adapter notes

## `bun add` rewrites your range

`bun add pkg@1.2.3` writes an **exact** version (`"1.2.3"`), discarding the
caret. Restore `"^1.2.3"` in `package.json` afterwards and re-run `bun install`
so the lock matches. It does preserve the dep/devDep section correctly — only
the range needs fixing. Confirm with `git diff frontend/package.json` that
nothing moved sections.

## `typecheck` is not `build`

`bun run typecheck` runs `tsc --noEmit` against the solution config and passes
trivially. `bun run build` runs `tsc -b`, which actually resolves the
referenced projects. **The baseline metric is `build`.** A green `typecheck` on
a dependency PR means nothing.

## Cooldown is mechanical

`frontend/bunfig.toml` sets `minimumReleaseAge = 1209600` (14 days), so
`bun add`/`bun install` refuse anything newer. A refusal is the policy working
— do not add a `minimumReleaseAgeExcludes` entry to get around it.

The exception is `overrides`: they bypass the check entirely. Run
`check_cooldown.py --adapter bun <pkg>@<version>` for every pin. `bun pm view
<pkg>@<version>` shows the same date interactively.

## `overrides` for transitive CVEs

`bun audit` findings usually sit in packages with no direct entry in
`package.json` (`brace-expansion` under `eslint`, `picomatch` under `vite`,
`protocol-buffers-schema` under `plotly.js`). Force them:

```jsonc
// frontend/package.json
"overrides": {
  "brace-expansion": "^5.0.9",
  "picomatch": "^4.0.5"
}
```

Forcing `minimatch`/`picomatch` under `eslint` and `typescript-eslint` is
exactly what silently breaks linting. Unchanged `build` and `lint` counts are
the evidence that both still execute — cite them.

## `baseline_tools`

`eslint`, `typescript`, `typescript-eslint`, and the eslint plugins produce the
numbers the batch is verified against. When one is in the batch, read the
findings diff rather than trusting the count.

Measured here: merging `#186` (`eslint-plugin-react-hooks` 7.0.1 → 7.1.1 — a
dev patch, textbook low tier) raised the lint count from 6 to 13. All seven new
findings were `react-hooks/set-state-in-effect` in `PricingPage.tsx`,
`TradeTaggingPage.tsx`, and `TradesTable.tsx`; not one line of source had
changed. Batch a bump like that with other packages and the counts stop meaning
anything for the whole PR.

## Reading the eslint count

The metric anchors on the summary's parenthesis — `(13 errors, 0 warnings)`.
A bare `([0-9]+) error` also matches text inside individual findings, so it can
report a number that has nothing to do with the total.
