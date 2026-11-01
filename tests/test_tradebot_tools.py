"""Characterization tests for the tradebot tool registry."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.services import tradebot_agent

SNAPSHOT_PATH = Path(__file__).parent / "snapshots" / "tradebot_tool_specs.json"


def _load_or_write_snapshot(specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the committed snapshot, writing it first when missing or when UPDATE_SNAPSHOTS is set."""
    if not SNAPSHOT_PATH.exists() or os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(specs, indent=2) + "\n", encoding="utf-8")
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


def test_tool_specs_match_snapshot() -> None:
    """The specs sent to the LLM stay identical; compared as parsed JSON, so key order is irrelevant."""
    live = json.loads(json.dumps(tradebot_agent._TOOL_SPECS))
    assert live == _load_or_write_snapshot(live)
