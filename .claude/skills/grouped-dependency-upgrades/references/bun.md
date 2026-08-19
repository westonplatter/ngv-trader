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
