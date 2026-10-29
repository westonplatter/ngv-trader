"""The MCP tag and task tools are thin wrappers that record the agent as the author."""

from __future__ import annotations

from typing import Any

import pytest

from src.mcp import semantic_server


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any, Any]]:
    recorded: list[tuple[str, str, Any, Any]] = []

    def fake_api(method: str, path: str, body: Any = None, params: Any = None) -> dict:
        recorded.append((method, path, body, params))
        return {}

    monkeypatch.setattr(semantic_server, "_api", fake_api)
    monkeypatch.setenv("NGV_AGENT_NAME", "desk-bot")
    return recorded


def test_writes_are_attributed_to_the_agent(calls: list) -> None:
    items = [{"entity_type": "trade", "id": 1}]
    semantic_server.tag_items(["oil"], items)
    semantic_server.create_task("Roll", links=items)
    semantic_server.link_task(7, items)

    assert [(method, path) for method, path, _, _ in calls] == [("POST", "/tag-links"), ("POST", "/tasks"), ("POST", "/tasks/7/links")]
    assert {body["created_by"] for _, _, body, _ in calls} == {"agent:desk-bot"}


def test_find_by_tags_passes_filters(calls: list) -> None:
    semantic_server.find_by_tags(all_tags=["oil"], none_tags=["risk-off"], entity_type="position")
    method, path, _, params = calls[0]
    assert (method, path) == ("GET", "/tags/search")
    assert params["all"] == ["oil"] and params["none"] == ["risk-off"] and params["entity_type"] == "position"


def test_update_task_sends_only_given_fields(calls: list) -> None:
    semantic_server.update_task(3, status="done")
    assert calls == [("PATCH", "/tasks/3", {"status": "done"}, None)]


def test_no_rename_merge_or_archive_tools() -> None:
    for name in ("rename_tag", "merge_tags", "archive_tag"):
        assert not hasattr(semantic_server, name)
