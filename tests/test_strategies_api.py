"""Strategies as their own table: CRUD, group assignment, filters, and the report."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import TradeGroup
from tests.trade_group_factories import CON_CL, make_account, make_exec_id, make_execution

API = "/api/v1"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose requests run inside the test's rolled-back session."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _create_strategy(client: TestClient, name: str) -> dict:
    response = client.post(f"{API}/strategies", json={"name": name, "created_by": "test"})
    assert response.status_code == 201, response.text
    return response.json()


def _create_group(client: TestClient, name: str, strategy_id: int | None) -> dict:
    response = client.post(f"{API}/trade-groups", json={"name": name, "strategy_id": strategy_id})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_strategy_is_idempotent_on_normalized_name(client: TestClient) -> None:
    first = _create_strategy(client, "Leap  + Weeklies")
    second = _create_strategy(client, "leap + weeklies")

    assert second["id"] == first["id"]
    assert first["name"] == "Leap  + Weeklies"
    assert first["normalized_name"] == "leap + weeklies"


def test_list_rename_archive_unarchive(client: TestClient) -> None:
    strategy = _create_strategy(client, "Wheel")
    other = _create_strategy(client, "Calendar")

    assert client.patch(f"{API}/strategies/{strategy['id']}", json={"name": "calendar"}).status_code == 409
    renamed = client.patch(f"{API}/strategies/{strategy['id']}", json={"name": "Covered wheel"}).json()
    assert renamed["name"] == "Covered wheel"

    assert client.get(f"{API}/strategies", params={"q": "WHEEL"}).json()[0]["id"] == strategy["id"]

    client.post(f"{API}/strategies/{other['id']}/archive")
    active_ids = {row["id"] for row in client.get(f"{API}/strategies").json()}
    assert other["id"] not in active_ids
    all_ids = {row["id"] for row in client.get(f"{API}/strategies", params={"include_archived": "true"}).json()}
    assert other["id"] in all_ids

    assert client.post(f"{API}/strategies/{other['id']}/unarchive").json()["archived_at"] is None


def test_delete_strategy_blocked_while_a_group_uses_it(client: TestClient) -> None:
    strategy = _create_strategy(client, "Wheel")
    group = _create_group(client, "Wheel May", strategy["id"])

    assert client.delete(f"{API}/strategies/{strategy['id']}").status_code == 409

    client.patch(f"{API}/trade-groups/{group['id']}", json={"strategy_id": None})
    assert client.delete(f"{API}/strategies/{strategy['id']}").status_code == 204


def test_group_strategy_assignment_and_filters(client: TestClient) -> None:
    wheel = _create_strategy(client, "Wheel")
    leaps = _create_strategy(client, "Leap + Weeklies")
    group = _create_group(client, "May campaign", wheel["id"])
    assert group["strategy_id"] == wheel["id"]

    detail = client.get(f"{API}/trade-groups/{group['id']}").json()
    assert detail["primary_strategy_value"] == "Wheel"
    # Free-form tags are separate from the strategy.
    assert detail["tags"] == []

    listed = client.get(f"{API}/trade-groups", params={"strategy": "wheel"}).json()
    assert [row["id"] for row in listed] == [group["id"]]
    assert listed[0]["primary_strategy_value"] == "Wheel"
    assert client.get(f"{API}/trade-groups", params={"strategy": "Leap + Weeklies"}).json() == []

    # Free-text search matches the strategy name as well as the group name.
    assert [row["id"] for row in client.get(f"{API}/trade-groups", params={"q": "whe"}).json()] == [group["id"]]

    # Omitting strategy_id leaves it alone; sending it reassigns.
    assert client.patch(f"{API}/trade-groups/{group['id']}", json={"notes": "x"}).json()["strategy_id"] == wheel["id"]
    assert client.patch(f"{API}/trade-groups/{group['id']}", json={"strategy_id": leaps["id"]}).json()["strategy_id"] == leaps["id"]


def test_unknown_strategy_id_is_404(client: TestClient) -> None:
    assert client.post(f"{API}/trade-groups", json={"name": "x", "strategy_id": 999_999}).status_code == 404
    group = _create_group(client, "y", None)
    assert client.patch(f"{API}/trade-groups/{group['id']}", json={"strategy_id": 999_999}).status_code == 404


def test_report_groups_by_strategy(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    wheel = _create_strategy(client, "Wheel")
    group = _create_group(client, "May campaign", wheel["id"])
    make_execution(
        db_session,
        group=db_session.get(TradeGroup, group["id"]),
        account=account,
        con_id=CON_CL,
        realized=0.0,
        exec_id=make_exec_id(50000001),
    )
    db_session.flush()

    report = client.get(f"{API}/reports/pnl/trade-groups", params={"group_by": "strategy"}).json()
    assert [row["key"] for row in report["rows"]] == ["Wheel"]
    assert client.get(f"{API}/reports/pnl/trade-groups", params={"group_by": "theme"}).status_code == 400


def test_theme_routes_are_gone(client: TestClient) -> None:
    assert client.get(f"{API}/themes").status_code == 404


def test_renamed_fields_are_rejected_not_ignored(client: TestClient) -> None:
    """An old client must get an error, not an unassigned group or an unfiltered list."""
    response = client.post(f"{API}/trade-groups", json={"name": "x", "strategy_tag_id": 1})
    assert response.status_code == 422
    assert "strategy_id" in response.text
    assert client.get(f"{API}/trade-groups", params={"strategy_tag": "wheel"}).status_code == 400
    assert client.get(f"{API}/trade-groups", params={"theme_tag": "oil"}).status_code == 400
    # Fields that were dropped without a rename stay harmless.
    assert client.post(f"{API}/trade-groups", json={"name": "y", "source": "manual"}).status_code == 201
