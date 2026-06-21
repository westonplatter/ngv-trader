#!/bin/bash
# SessionStart hook: install backend + frontend deps so tests/linters work
# in Claude Code on the web. Idempotent and non-interactive.
set -euo pipefail

# Only run in the remote (web) environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

# Backend: sync Python deps incl. the dev group (typer/ruff/ipdb).
# pyproject sets default-groups = [], so --group dev is required for
# scripts/check.py (typer) and ruff to be available.
echo "[session-start] uv sync --group dev"
uv sync --group dev

# Frontend: install JS deps with bun.
echo "[session-start] bun install (frontend)"
(cd frontend && bun install)

echo "[session-start] done"
