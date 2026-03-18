# Spec: Migrate Frontend from Node.js/npm to Bun

## Complexity: 1/5

## Purpose

Replace Node.js and npm with Bun as the JavaScript runtime and package manager for the frontend, improving install and dev server speed.

## Problem

- The frontend uses Node.js with explicit `node ./node_modules/vite/bin/vite.js` invocations in package.json scripts, which is verbose and non-standard
- npm installs are slower than Bun's dependency resolution
- No particular reason to stay on Node.js — the stack (Vite, React, Tailwind) is fully Bun-compatible

## Scope

- Replace npm with Bun for dependency management in `frontend/`
- Update package.json scripts to use Bun
- Replace `package-lock.json` with `bun.lock`
- Verify Vite dev server, build, and lint all work under Bun

## Non-goals

- Migrating the Python backend to a different runtime
- Rewriting any application code (React components, hooks, etc.)
- Changing the build tool (Vite stays)
- Adopting Bun-specific APIs (e.g., `Bun.serve`) in application code

## Current State

- Runtime: Node.js (version unspecified, assumed system default)
- Package manager: npm with `package-lock.json`
- Build tool: Vite 7.x with React and Tailwind plugins
- Scripts in `package.json` use `node ./node_modules/vite/bin/vite.js` directly
- Dependencies: React 19, react-router-dom, plotly.js, @ai-sdk/react, ai, dnd-kit

## Desired Outcome

- `bun install` resolves all dependencies and produces `bun.lock`
- `bun run dev` starts the Vite dev server with HMR working
- `bun run build` produces a production build in `dist/`
- `bun run lint` runs ESLint successfully
- No `package-lock.json` or Node.js-specific artifacts remain

## Functional Plan

1. Install dependencies with Bun
   - Run `bun install` in `frontend/`
   - Generates `bun.lock`
2. Update `package.json` scripts
   - `"dev": "bunx --bun vite"`
   - `"build": "bun run tsc -b && bunx --bun vite build"`
   - `"lint": "bunx eslint ."`
   - `"preview": "bunx --bun vite preview"`
   - `bunx --bun` uses Bun's runtime for Vite (faster); plain `bunx` is the fallback if compatibility issues arise
3. Remove `package-lock.json`
4. Remove `node_modules/` and reinstall with `bun install` for a clean slate
5. Smoke test all scripts (`dev`, `build`, `lint`, `preview`)

## Risks

- Some npm packages with native addons may not work under Bun's runtime — unlikely here since the dependency tree is pure JS/TS
- `bunx --bun` runs Vite under Bun's runtime rather than Node; if any Vite plugin assumes Node-specific behavior, this could break — fallback is to drop the `--bun` flag

## Acceptance Criteria

- `bun install` completes without errors
- `bun run dev` starts Vite and the app loads in browser with HMR working
- `bun run build` produces `dist/` with no errors
- `bun run lint` passes
- `package-lock.json` is removed from the repo
- `bun.lock` is committed

## Related Files

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/.gitignore`
