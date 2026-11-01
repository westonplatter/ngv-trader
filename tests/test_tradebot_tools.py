"""Tests for the tradebot tool registry: the published specs, argument handling, and the handlers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from src.models import Account, Job
from src.services import tradebot_agent
from src.services.jobs import JOB_TYPE_CONTRACTS_SYNC, JOB_TYPE_ORDER_FETCH_SYNC, JOB_TYPE_POSITIONS_SYNC_FLEXQUERY

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


# --- registry --------------------------------------------------------------------------------------------


def test_specs_and_handlers_are_derived_from_the_one_registry() -> None:
    names = [registered.name for registered in tradebot_agent.TOOLS]
    assert len(names) == len(set(names))
    assert [spec["function"]["name"] for spec in tradebot_agent._TOOL_SPECS] == names
    assert list(tradebot_agent._TOOL_HANDLERS) == names


def test_query_metric_is_registered_with_its_dynamic_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tradebot_agent, "TOOLS", [])
    monkeypatch.setattr(tradebot_agent, "_build_query_metric_schema", lambda: ("desc", {"type": "object", "properties": {}}))
    tradebot_agent._register_query_metric_tool()
    [registered] = tradebot_agent.TOOLS
    assert registered.name == "query_metric"
    assert registered.spec()["function"]["parameters"] == {"type": "object", "properties": {}}


def test_query_metric_is_skipped_everywhere_when_the_semantic_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> tuple[str, dict[str, Any]]:
        raise RuntimeError("bad model file")

    monkeypatch.setattr(tradebot_agent, "TOOLS", [])
    monkeypatch.setattr(tradebot_agent, "_build_query_metric_schema", broken)
    tradebot_agent._register_query_metric_tool()
    assert tradebot_agent.TOOLS == []


def test_duplicate_tool_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate"):
        tradebot_agent._register_tool(tradebot_agent.TOOLS[0])


# --- _execute_tool_call: argument handling ----------------------------------------------------------------


def _run(db_session: Session, tool_name: str, arguments_json: str = "{}", user_text: str = "hello") -> dict[str, Any]:
    return tradebot_agent._execute_tool_call(db_session, user_text, tool_name, arguments_json)


def test_unknown_tool(db_session: Session) -> None:
    assert _run(db_session, "no_such_tool") == {"ok": False, "error": "Unknown tool 'no_such_tool'."}


def test_arguments_that_are_not_json(db_session: Session) -> None:
    assert _run(db_session, "list_jobs", "{not json") == {
        "ok": False,
        "error": "Arguments for tool 'list_jobs' were not valid JSON.",
    }


@pytest.mark.parametrize("arguments_json", ["[1, 2]", '"text"', "7", "null"])
def test_arguments_that_are_not_an_object(db_session: Session, arguments_json: str) -> None:
    assert _run(db_session, "list_jobs", arguments_json) == {
        "ok": False,
        "error": "Arguments for tool 'list_jobs' must be an object.",
    }


@pytest.mark.parametrize(
    ("tool_name", "arguments_json", "field"),
    [
        ("list_positions", '{"limit": 0}', "limit"),
        ("list_positions", '{"limit": 201}', "limit"),
        ("list_positions", '{"limit": "5"}', "limit"),
        ("list_positions", '{"limit": 2.5}', "limit"),
        ("list_jobs", '{"include_archived": "yes"}', "include_archived"),
        ("list_orders", '{"events_per_order": 21}', "events_per_order"),
        ("preview_order", '{"symbol": "CL", "side": "BUY"}', "quantity"),
        ("get_watch_list", "{}", "watch_list_id"),
        ("create_watch_list", '{"name": "   "}', "name"),
        ("lookup_contract", '{"symbol": " ", "sec_type": "FUT"}', "symbol"),
        ("trade_group_pnl", '{"group": ""}', "group"),
        ("trade_group_pnl", '{"group": true}', "group"),
        ("enqueue_positions_sync_job", '{"max_attempts": 11}', "max_attempts"),
    ],
)
def test_validation_failure_is_an_ok_false_error_naming_the_field(db_session: Session, tool_name: str, arguments_json: str, field: str) -> None:
    out = _run(db_session, tool_name, arguments_json)
    assert out["ok"] is False
    assert set(out) == {"ok", "error"}
    assert out["error"].startswith(f"Invalid arguments for tool '{tool_name}': ")
    assert f"'{field}" in out["error"]  # a union field is reported per member, e.g. 'group.str'


def test_tools_without_arguments_reject_any(db_session: Session) -> None:
    out = _run(db_session, "list_accounts", '{"limit": 3}')
    assert out["ok"] is False
    assert "'limit'" in out["error"]


def test_unknown_keys_are_ignored_by_tools_that_take_arguments(db_session: Session) -> None:
    out = _run(db_session, "list_positions", '{"limit": 1, "bogus": true}')
    assert out["ok"] is True


def test_empty_arguments_string_means_no_arguments(db_session: Session) -> None:
    out = _run(db_session, "list_positions", "   ")
    assert out["ok"] is True
    assert out["result"]["count"] == len(out["result"]["positions"])


def test_handler_errors_keep_the_ok_false_shape(db_session: Session) -> None:
    out = _run(db_session, "get_watch_list", '{"watch_list_id": 999999}')
    assert out == {"ok": False, "error": "Watch list #999999 not found."}


# --- _execute_tool_call: handlers -------------------------------------------------------------------------


def test_list_accounts_masks_the_account_number(db_session: Session) -> None:
    db_session.add(Account(account="U1234567", alias="Tradebot Test"))
    db_session.flush()
    out = _run(db_session, "list_accounts")
    assert out["ok"] is True
    [row] = [a for a in out["result"]["accounts"] if a["alias"] == "Tradebot Test"]
    assert "U1234567" not in json.dumps(row)


def test_preview_order_applies_defaults_and_blank_means_default(db_session: Session) -> None:
    account = Account(account="U1234567", alias="Tradebot Test")
    db_session.add(account)
    db_session.flush()
    args = {"account": "u1234567", "symbol": " cl ", "side": "buy", "quantity": 2, "sec_type": " ", "tif": "", "request_text": " "}
    out = _run(db_session, "preview_order", json.dumps(args), user_text="buy two crude")
    assert out["ok"] is True, out
    preview = out["result"]["preview"]
    assert preview["account_id"] == account.id
    assert (preview["symbol"], preview["side"], preview["quantity"]) == ("CL", "BUY", 2)
    assert (preview["sec_type"], preview["currency"], preview["order_type"], preview["tif"]) == ("FUT", "USD", "MKT", "DAY")
    assert preview["limit_price"] is None
    assert preview["request_text"] == "buy two crude"
    assert preview["source"] == "tradebot-llm"
    assert out["result"]["message"] == "Preview only. No order was queued."


def test_preview_order_needs_an_account(db_session: Session) -> None:
    out = _run(db_session, "preview_order", '{"symbol": "CL", "side": "BUY", "quantity": 1}')
    assert out == {"ok": False, "error": "Provide 'account_id' or 'account' (alias/account number)."}


def test_preview_order_ignores_the_limit_price_of_a_market_order(db_session: Session) -> None:
    db_session.add(Account(account="U1234567"))
    db_session.flush()
    args = {"account": "U1234567", "symbol": "CL", "side": "SELL", "quantity": 1, "limit_price": -1}
    out = _run(db_session, "preview_order", json.dumps(args))
    assert out["ok"] is True, out
    assert out["result"]["preview"]["limit_price"] is None


def _queued_job(db_session: Session, out: dict[str, Any]) -> Job:
    assert out["ok"] is True, out
    job = db_session.get(Job, out["result"]["job_id"])
    assert job is not None
    return job


@pytest.mark.parametrize(
    ("tool_name", "job_type"),
    [
        ("enqueue_positions_sync_job", JOB_TYPE_POSITIONS_SYNC_FLEXQUERY),
        ("enqueue_order_fetch_sync_job", JOB_TYPE_ORDER_FETCH_SYNC),
        ("enqueue_contracts_sync_job", JOB_TYPE_CONTRACTS_SYNC),
    ],
)
def test_enqueue_tools_queue_one_job_and_report_it(db_session: Session, tool_name: str, job_type: str) -> None:
    out = _run(db_session, tool_name, "{}", user_text="sync please")
    job = _queued_job(db_session, out)
    assert out["result"] == {"job_id": job.id, "job_type": job_type, "status": "queued", "max_attempts": 3}
    assert (job.payload, job.source, job.request_text) == ({}, "tradebot-llm", "sync please")


def test_enqueue_tools_take_request_text_and_max_attempts(db_session: Session) -> None:
    out = _run(db_session, "enqueue_order_fetch_sync_job", '{"request_text": " pull orders ", "max_attempts": 7}', user_text="ignored")
    job = _queued_job(db_session, out)
    assert (job.request_text, job.max_attempts) == ("pull orders", 7)


def test_enqueue_contracts_sync_defaults_to_cl_when_only_sec_type_is_given(db_session: Session) -> None:
    job = _queued_job(db_session, _run(db_session, "enqueue_contracts_sync_job", '{"sec_type": "fut"}'))
    [spec] = job.payload["specs"]
    assert (spec["symbol"], spec["sec_type"]) == ("CL", "FUT")
    assert spec["exchange"]


def test_enqueue_contracts_sync_with_a_symbol(db_session: Session) -> None:
    job = _queued_job(db_session, _run(db_session, "enqueue_contracts_sync_job", '{"symbol": "nq", "sec_type": "FUT"}'))
    [spec] = job.payload["specs"]
    assert (spec["symbol"], spec["sec_type"]) == ("NQ", "FUT")
    assert spec["exchange"]


def test_create_and_get_watch_list(db_session: Session) -> None:
    created = _run(db_session, "create_watch_list", '{"name": "  Core  ", "description": " "}')
    assert created["ok"] is True
    assert created["result"]["name"] == "Core"
    assert created["result"]["description"] is None
    fetched = _run(db_session, "get_watch_list", json.dumps({"watch_list_id": created["result"]["id"]}))
    assert fetched["result"]["instruments"] == []


def test_check_watchlist_job_reports_the_job_state(db_session: Session) -> None:
    job = tradebot_agent.enqueue_job(db_session, tradebot_agent.JOB_TYPE_WATCHLIST_ADD_INSTRUMENT, payload={}, source="test", request_text=None)
    out = _run(db_session, "check_watchlist_job", json.dumps({"job_id": job.id}))
    assert out["result"]["status"] == "queued"
    job.status = "failed"
    job.last_error = "boom"
    db_session.flush()
    out = _run(db_session, "check_watchlist_job", json.dumps({"job_id": job.id}))
    assert out["result"] == {"status": "failed", "error": "boom"}
