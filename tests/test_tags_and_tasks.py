"""Free-form tags and tasks: catalog, attach/detach, search, sync hooks, and the task API."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from src.models import LiveExecution, LivePosition, TagLink, TaskLink
from src.services.group_link_carryover import carry_over_link_to_executions, carry_over_settled_group_links
from src.services.intraday_overlay import ct_date
from src.services.item_links import end_flat_position_tags, inherit_order_links
from src.services.tags import normalize_tag_value
from tests.trade_group_factories import (
    CON_CL,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
    make_live_position,
    make_position,
    now,
)

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


def _tag(client: TestClient, tags: list, items: list[dict], created_by: str = "user") -> dict:
    response = client.post(f"{API}/tag-links", json={"tags": tags, "items": items, "created_by": created_by})
    assert response.status_code == 201, response.text
    return response.json()


def _untag(client: TestClient, tags: list, items: list[dict]) -> dict:
    response = client.request("DELETE", f"{API}/tag-links", json={"tags": tags, "items": items})
    assert response.status_code == 200, response.text
    return response.json()


def _live_order(session: Session, account, perm_id: int, seqs: list[int], con_id: int = CON_CL) -> list[LiveExecution]:
    fills = []
    for seq in seqs:
        fill = make_live_execution(session, account=account, con_id=con_id, exec_id=make_exec_id(seq))
        fill.ib_perm_id = perm_id
        fills.append(fill)
    session.flush()
    return fills


# --------------------------------------------------------------------------
# Catalog
# --------------------------------------------------------------------------


def test_normalization_folds_case_spaces_dashes_and_underscores() -> None:
    assert normalize_tag_value("  Long  Beta ") == normalize_tag_value("long_beta") == normalize_tag_value("LONG-beta") == "long-beta"


def test_create_returns_existing_tag_on_normalized_match(client: TestClient) -> None:
    first = client.post(f"{API}/tags", json={"value": "Risk Off", "color": "#cc0000"}).json()
    second = client.post(f"{API}/tags", json={"value": "risk_off"}).json()
    assert second["id"] == first["id"]
    assert first["value"] == "Risk Off"
    assert first["color"] == "#cc0000"


def test_created_by_must_be_user_or_agent(client: TestClient) -> None:
    assert client.post(f"{API}/tags", json={"value": "oil", "created_by": "agent:local-llm"}).status_code == 201
    assert client.post(f"{API}/tags", json={"value": "oil", "created_by": "someone"}).status_code == 400


def test_rename_conflict_merge_and_archive(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "Crude", account.id)
    oil = client.post(f"{API}/tags", json={"value": "oil"}).json()
    crude = client.post(f"{API}/tags", json={"value": "crude"}).json()
    _tag(client, [oil["id"], crude["id"]], [{"entity_type": "trade_group", "id": group.id}])

    assert client.patch(f"{API}/tags/{crude['id']}", json={"value": "OIL"}).status_code == 409
    merged = client.post(f"{API}/tags/{crude['id']}/merge", json={"into_tag_id": oil["id"]}).json()
    assert merged["usage"] == {"trade_group": 1}
    assert [t["id"] for t in client.get(f"{API}/tags").json()] == [oil["id"]]

    client.post(f"{API}/tags/{oil['id']}/archive")
    assert client.get(f"{API}/tags").json() == []
    assert len(client.get(f"{API}/tags", params={"include_archived": "true"}).json()) == 1


# --------------------------------------------------------------------------
# Attaching, fan-out, search
# --------------------------------------------------------------------------


def test_attach_by_name_creates_tags_and_annotates_reads(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "Crude", account.id)
    execution = make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(60000001))
    make_position(db_session, account=account, con_id=CON_CL)

    result = _tag(
        client,
        ["downside put selling", "long-beta"],
        [
            {"entity_type": "trade", "id": execution.trade_id},
            {"entity_type": "position", "account_id": account.id, "con_id": CON_CL},
            {"entity_type": "trade_group", "id": group.id},
        ],
        created_by="agent:local-llm",
    )
    assert result["changed"] == 6
    # Re-applying is a no-op.
    assert _tag(client, ["long beta"], [{"entity_type": "trade", "id": execution.trade_id}])["changed"] == 0

    trades = client.get(f"{API}/trade-executions").json()
    assert {t["value"] for t in trades[0]["tags"]} == {"downside put selling", "long-beta"}
    assert trades[0]["tags"][0]["created_by"] == "agent:local-llm"
    positions = client.get(f"{API}/positions").json()
    assert len(positions[0]["tags"]) == 2
    groups = client.get(f"{API}/trade-groups").json()
    assert len(groups[0]["tags"]) == 2
    assert len(client.get(f"{API}/trade-groups/{group.id}").json()["tags"]) == 2


def test_tagging_a_live_fill_fans_out_to_its_whole_order(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    first, second = _live_order(db_session, account, perm_id=900001, seqs=[61000001, 61000002])
    other = _live_order(db_session, account, perm_id=900002, seqs=[61000003])[0]

    assert _tag(client, ["oil"], [{"entity_type": "live_execution", "ib_exec_id": first.ib_exec_id}])["changed"] == 2

    tagged = set(db_session.execute(select(TagLink.ib_exec_id).where(TagLink.entity_type == "live_execution")).scalars())
    assert tagged == {first.ib_exec_id, second.ib_exec_id}
    assert other.ib_exec_id not in tagged

    # Removing from one fill removes it from the whole order.
    assert _untag(client, ["oil"], [{"entity_type": "live_execution", "ib_exec_id": second.ib_exec_id}])["changed"] == 2


def test_search_all_any_none(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    crude = make_group(db_session, "Crude", account.id)
    gas = make_group(db_session, "Gas", account.id)
    index = make_group(db_session, "Index", account.id)
    _tag(client, ["oil", "risk-off"], [{"entity_type": "trade_group", "id": crude.id}])
    _tag(client, ["oil"], [{"entity_type": "trade_group", "id": gas.id}])
    _tag(client, ["long-beta"], [{"entity_type": "trade_group", "id": index.id}])

    def labels(**params) -> set[str]:
        return {row["label"] for row in client.get(f"{API}/tags/search", params=params).json()["items"]}

    assert labels(all="oil,risk off") == {"Crude"}
    assert labels(any=["risk-off", "long-beta"]) == {"Crude", "Index"}
    assert labels(any="oil", none="risk-off") == {"Gas"}
    assert labels(entity_type="trade_group", none="oil") == {"Index"}


# --------------------------------------------------------------------------
# Sync hooks
# --------------------------------------------------------------------------


def test_live_tags_and_tasks_move_to_the_settled_trade(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    fill = _live_order(db_session, account, perm_id=900010, seqs=[62000001])[0]
    _tag(client, ["oil"], [{"entity_type": "live_execution", "ib_exec_id": fill.ib_exec_id}])
    task = client.post(
        f"{API}/tasks",
        json={"title": "Roll before expiry", "links": [{"entity_type": "live_execution", "ib_exec_id": fill.ib_exec_id}]},
    ).json()

    settled = make_execution(db_session, group=None, account=account, con_id=CON_CL, exec_id=fill.ib_exec_id)
    carry_over_settled_group_links(db_session, {fill.ib_exec_id})
    db_session.flush()

    links = db_session.execute(select(TagLink)).scalars().all()
    assert [(link.entity_type, link.trade_id) for link in links] == [("trade", settled.trade_id)]
    task_links = db_session.execute(select(TaskLink).where(TaskLink.task_id == task["id"])).scalars().all()
    assert [(link.entity_type, link.trade_id) for link in task_links] == [("trade", settled.trade_id)]


def test_combo_summary_tags_fan_out_onto_settled_legs(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    summary = _live_order(db_session, account, perm_id=900020, seqs=[63000001])[0]
    _tag(client, ["calendar"], [{"entity_type": "live_execution", "ib_exec_id": summary.ib_exec_id}])
    leg_a = make_execution(db_session, group=None, account=account, con_id=CON_CL, exec_id=make_exec_id(63000002))
    leg_b = make_execution(db_session, group=None, account=account, con_id=CON_NG, exec_id=make_exec_id(63000003))

    carry_over_link_to_executions(db_session, summary.ib_exec_id, [leg_a.id, leg_b.id])
    db_session.flush()

    trade_ids = set(db_session.execute(select(TagLink.trade_id).where(TagLink.entity_type == "trade")).scalars())
    assert trade_ids == {leg_a.trade_id, leg_b.trade_id}
    assert db_session.execute(select(TagLink).where(TagLink.entity_type == "live_execution")).first() is None


def test_late_partial_fill_inherits_its_orders_tags(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    first = _live_order(db_session, account, perm_id=900030, seqs=[64000001])[0]
    _tag(client, ["oil"], [{"entity_type": "live_execution", "ib_exec_id": first.ib_exec_id}])
    late = _live_order(db_session, account, perm_id=900030, seqs=[64000002])[0]
    unrelated = _live_order(db_session, account, perm_id=900031, seqs=[64000003])[0]

    assert inherit_order_links(db_session) == 1
    db_session.flush()
    tagged = set(db_session.execute(select(TagLink.ib_exec_id)).scalars())
    assert tagged == {first.ib_exec_id, late.ib_exec_id}
    assert unrelated.ib_exec_id not in tagged


def test_position_tags_end_only_when_flat_everywhere_and_snapshot_is_current(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    position = make_position(db_session, account=account, con_id=CON_CL, as_of_date=ct_date(now()) - timedelta(days=1))
    live = make_live_position(db_session, account=account, con_id=CON_CL)
    item = {"entity_type": "position", "account_id": account.id, "con_id": CON_CL}
    _tag(client, ["oil"], [item])

    # Held in both: stays open.
    assert end_flat_position_tags(db_session) == 0
    # Flat in both, but the settled snapshot predates the tag (T-1): absence proves nothing.
    db_session.delete(position)
    db_session.delete(live)
    other = make_position(db_session, account=account, con_id=CON_NG, as_of_date=ct_date(now()) - timedelta(days=1))
    db_session.flush()
    assert end_flat_position_tags(db_session) == 0
    # Once a snapshot dated on/after the tag's day lands without it, the tag ends.
    other.as_of_date = ct_date(now())
    db_session.flush()
    assert end_flat_position_tags(db_session) == 1
    db_session.flush()

    assert client.get(f"{API}/tags/search", params={"all": "oil"}).json()["items"] == []
    ended = client.get(f"{API}/tags/search", params={"all": "oil", "include_ended": "true"}).json()["items"]
    assert ended[0]["tags"][0]["ended_at"] is not None
    # Re-tagging a re-opened position opens a fresh link.
    db_session.add(LivePosition(account_id=account.id, con_id=CON_CL, symbol="CL", position=1.0, avg_cost=1.0))
    db_session.flush()
    assert _tag(client, ["oil"], [item])["changed"] == 1


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------


def test_task_crud_status_and_done_toggle(client: TestClient) -> None:
    created = client.post(f"{API}/tasks", json={"title": "Check margin", "notes": "before FOMC", "tags": ["risk-off"]}).json()
    assert created["status"] == "todo"
    assert [t["value"] for t in created["tags"]] == ["risk-off"]

    done = client.patch(f"{API}/tasks/{created['id']}", json={"status": "done"}).json()
    assert done["completed_at"] is not None
    assert client.get(f"{API}/tasks").json() == []
    assert [t["id"] for t in client.get(f"{API}/tasks", params={"include_done": "true"}).json()] == [created["id"]]

    reopened = client.patch(f"{API}/tasks/{created['id']}", json={"status": "in_progress"}).json()
    assert reopened["completed_at"] is None
    assert client.patch(f"{API}/tasks/{created['id']}", json={"status": "blocked"}).status_code == 400

    assert client.delete(f"{API}/tasks/{created['id']}").status_code == 204
    assert client.get(f"{API}/tasks/{created['id']}").status_code == 404


def test_task_links_filters_and_counts(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "Crude", account.id)
    execution = make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(65000001))
    make_position(db_session, account=account, con_id=CON_CL)
    strategy = client.post(f"{API}/strategies", json={"name": "Wheel", "created_by": "test"}).json()

    task = client.post(
        f"{API}/tasks",
        json={
            "title": "Cover the short call",
            "links": [
                {"entity_type": "strategy", "id": strategy["id"]},
                {"entity_type": "trade_group", "id": group.id},
                {"entity_type": "trade", "id": execution.trade_id},
            ],
        },
    ).json()
    linked = client.post(
        f"{API}/tasks/{task['id']}/links",
        json={"items": [{"entity_type": "position", "account_id": account.id, "con_id": CON_CL}], "created_by": "agent:local-llm"},
    ).json()
    assert {link["entity_type"] for link in linked["links"]} == {"strategy", "trade_group", "trade", "position"}
    position_link = next(link for link in linked["links"] if link["entity_type"] == "position")
    assert position_link["details"]["open"] is True

    assert [t["id"] for t in client.get(f"{API}/tasks", params={"strategy_id": strategy["id"]}).json()] == [task["id"]]
    assert [t["id"] for t in client.get(f"{API}/tasks", params={"trade_group_id": group.id}).json()] == [task["id"]]
    assert [t["id"] for t in client.get(f"{API}/tasks", params={"symbol": "cl"}).json()] == [task["id"]]
    assert client.get(f"{API}/tasks", params={"symbol": "NG"}).json() == []

    assert client.get(f"{API}/trade-groups/{group.id}").json()["open_task_count"] == 1
    assert client.get(f"{API}/positions").json()[0]["open_task_count"] == 1
    assert client.get(f"{API}/trade-executions").json()[0]["open_task_count"] == 1

    unlinked = client.request(
        "DELETE",
        f"{API}/tasks/{task['id']}/links",
        json={"items": [{"entity_type": "strategy", "id": strategy["id"]}]},
    ).json()
    assert "strategy" not in {link["entity_type"] for link in unlinked["links"]}


def test_deleting_a_group_drops_its_links_not_the_task(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "Crude", account.id)
    task = client.post(f"{API}/tasks", json={"title": "Review", "links": [{"entity_type": "trade_group", "id": group.id}]}).json()
    _tag(client, ["oil"], [{"entity_type": "trade_group", "id": group.id}])

    assert client.delete(f"{API}/trade-groups/{group.id}").status_code == 204
    db_session.expire_all()
    assert client.get(f"{API}/tasks/{task['id']}").json()["links"] == []
    assert db_session.execute(select(TagLink)).first() is None


def test_unknown_items_are_rejected(client: TestClient) -> None:
    response = client.post(f"{API}/tag-links", json={"tags": ["oil"], "items": [{"entity_type": "trade", "id": 999_999}]})
    assert response.status_code == 404
    response = client.post(f"{API}/tag-links", json={"tags": ["oil"], "items": [{"entity_type": "strategy", "id": 1}]})
    assert response.status_code == 400



def test_task_with_unknown_tag_id_is_404(client: TestClient) -> None:
    response = client.post(f"{API}/tasks", json={"title": "x", "tags": [999_999]})
    assert response.status_code == 404
    assert client.get(f"{API}/tasks").json() == []


def test_tag_list_limit_keeps_the_most_used(client: TestClient, db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "Crude", account.id)
    client.post(f"{API}/tags", json={"value": "aaa-unused"})
    _tag(client, ["zzz-used"], [{"entity_type": "trade_group", "id": group.id}])
    assert [t["value"] for t in client.get(f"{API}/tags", params={"limit": 1}).json()] == ["zzz-used"]
