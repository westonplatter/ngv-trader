"""The entity-type registry in ``src.services.item_refs``: one spec per type, and
the key shapes each spec produces."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.domain.enums import EntityType
from src.models import TAG_ENTITY_TYPES, TASK_ENTITY_TYPES, TagLink, TaskLink
from src.services.item_descriptions import DESCRIBERS
from src.services.item_refs import ENTITY_SPECS, ItemRef, item_key, link_filter, link_item, spec_for

# (item, link-row columns, lookup key, columns link_filter matches on)
CASES: list[tuple[ItemRef, dict[str, Any], Any, list[str]]] = [
    (ItemRef(EntityType.TRADE, id=7), {"trade_id": 7}, 7, ["trade_id"]),
    (ItemRef(EntityType.TRADE_GROUP, id=8), {"trade_group_id": 8}, 8, ["trade_group_id"]),
    (ItemRef(EntityType.TASK, id=9), {"task_id": 9}, 9, ["task_id"]),
    (ItemRef(EntityType.STRATEGY, id=10), {"strategy_id": 10}, 10, ["strategy_id"]),
    (ItemRef(EntityType.POSITION, account_id=1, con_id=2), {"account_id": 1, "con_id": 2}, (1, 2), ["account_id", "con_id"]),
    (
        ItemRef(EntityType.LIVE_EXECUTION, account_id=1, con_id=2, ib_exec_id="exec-a"),
        {"ib_exec_id": "exec-a", "account_id": 1, "con_id": 2},
        "exec-a",
        ["ib_exec_id"],
    ),
]
IDS = [case[0].entity_type for case in CASES]


def test_every_entity_type_has_one_spec_and_one_describer() -> None:
    assert set(ENTITY_SPECS) == set(EntityType)
    assert set(DESCRIBERS) == set(EntityType)
    assert all(spec.entity_type == entity_type for entity_type, spec in ENTITY_SPECS.items())


def test_case_table_covers_every_entity_type() -> None:
    assert set(IDS) == set(EntityType)


def test_tag_and_task_subsets_are_registered() -> None:
    assert set(TAG_ENTITY_TYPES) <= set(ENTITY_SPECS)
    assert set(TASK_ENTITY_TYPES) <= set(ENTITY_SPECS)


@pytest.mark.parametrize(("item", "columns", "key", "matched"), CASES, ids=IDS)
def test_spec_key_shapes(item: ItemRef, columns: dict[str, Any], key: Any, matched: list[str]) -> None:
    assert item.key() == columns
    assert item_key(item) == key
    row: dict[str, Any] = {"id": None, "account_id": None, "con_id": None, "ib_exec_id": None, **columns}
    link: Any = SimpleNamespace(entity_type=item.entity_type, **row)
    assert link_item(link) == item
    assert spec_for(item.entity_type).row_key(link) == key


@pytest.mark.parametrize(("item", "columns", "key", "matched"), CASES, ids=IDS)
def test_link_filter_matches_type_then_key_columns(item: ItemRef, columns: dict[str, Any], key: Any, matched: list[str]) -> None:
    model = TagLink if item.entity_type in TAG_ENTITY_TYPES else TaskLink
    table = model.__tablename__
    clauses = [str(clause) for clause in link_filter(model, item)]
    assert clauses == [f"{table}.entity_type = :entity_type_1", *[f"{table}.{column} = :{column}_1" for column in matched]]
