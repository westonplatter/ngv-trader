"""A contract lookup miss queues a contracts.sync job; the API path never calls the broker."""

from __future__ import annotations

import json
import socket
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import Job, WatchListInstrument
from src.services import contract_lookup, tradebot_agent
from src.services.contract_lookup import find_contracts_with_fallback
from src.services.jobs import JOB_TYPE_CONTRACTS_SYNC
from tests.trade_group_factories import make_contract

CON_KNOWN = 400000001
KNOWN_SYMBOL = "ZZKNOWN"
UNKNOWN_SYMBOL = "ZZUNKNOWN"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test session already holds its DB connection; any new socket would be a broker call."""

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("contract lookup must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _contracts_sync_job_count(session: Session) -> int:
    return session.execute(select(func.count(Job.id)).where(Job.job_type == JOB_TYPE_CONTRACTS_SYNC)).scalar_one()


def test_the_broker_fetch_is_gone() -> None:
    assert not hasattr(contract_lookup, "_fetch_from_ibkr")
    assert not hasattr(contract_lookup, "Contract")
    assert not hasattr(contract_lookup, "get_engine")


def test_unknown_symbol_enqueues_exactly_one_contracts_sync_job(db_session: Session) -> None:
    before = _contracts_sync_job_count(db_session)

    lookup = find_contracts_with_fallback(db_session, UNKNOWN_SYMBOL, "STK")

    assert lookup.contracts == []
    assert _contracts_sync_job_count(db_session) == before + 1
    job = db_session.get(Job, lookup.pending_job_id)
    assert job is not None
    assert job.job_type == JOB_TYPE_CONTRACTS_SYNC
    assert job.status == "queued"
    assert job.payload == {"specs": [{"symbol": UNKNOWN_SYMBOL, "sec_type": "STK", "exchange": "SMART"}]}
    assert lookup.message is not None
    assert f"#{job.id}" in lookup.message


def test_known_futures_exchange_goes_into_the_job_spec(db_session: Session) -> None:
    lookup = find_contracts_with_fallback(db_session, "CL", "FUT", contract_expiry="19990101")

    job = db_session.get(Job, lookup.pending_job_id)
    assert job is not None
    assert job.payload == {"specs": [{"symbol": "CL", "sec_type": "FUT", "exchange": "NYMEX"}]}


def test_futures_symbol_without_a_known_exchange_still_queues_with_smart(db_session: Session) -> None:
    lookup = find_contracts_with_fallback(db_session, UNKNOWN_SYMBOL, "FUT")

    job = db_session.get(Job, lookup.pending_job_id)
    assert job is not None
    assert job.payload == {"specs": [{"symbol": UNKNOWN_SYMBOL, "sec_type": "FUT", "exchange": "SMART"}]}


def test_known_symbol_returns_contracts_and_enqueues_nothing(db_session: Session) -> None:
    make_contract(db_session, con_id=CON_KNOWN, symbol=KNOWN_SYMBOL)
    before = _contracts_sync_job_count(db_session)

    lookup = find_contracts_with_fallback(db_session, KNOWN_SYMBOL, "FUT")

    assert [c["con_id"] for c in lookup.contracts] == [CON_KNOWN]
    assert lookup.pending_job_id is None
    assert lookup.message is None
    assert _contracts_sync_job_count(db_session) == before


def test_lookup_contract_tool_reports_the_pending_job(db_session: Session) -> None:
    before = _contracts_sync_job_count(db_session)

    out = tradebot_agent._execute_tool_call(db_session, "front month?", "lookup_contract", json.dumps({"symbol": UNKNOWN_SYMBOL, "sec_type": "STK"}))

    assert out["ok"] is True, out
    result = out["result"]
    assert (result["symbol"], result["sec_type"], result["total_contracts"]) == (UNKNOWN_SYMBOL, "STK", 0)
    assert "front_month" not in result
    assert _contracts_sync_job_count(db_session) == before + 1
    job = db_session.get(Job, result["pending_job_id"])
    assert job is not None
    assert job.job_type == JOB_TYPE_CONTRACTS_SYNC
    assert result["message"]


def test_add_watch_list_instrument_on_a_miss_adds_nothing_and_reports_the_pending_job(db_session: Session) -> None:
    created = tradebot_agent._execute_tool_call(db_session, "", "create_watch_list", json.dumps({"name": "Core"}))
    watch_list_id = created["result"]["id"]
    before = _contracts_sync_job_count(db_session)

    args = {"watch_list_id": watch_list_id, "symbol": UNKNOWN_SYMBOL, "sec_type": "STK"}
    out = tradebot_agent._execute_tool_call(db_session, "add it", "add_watch_list_instrument", json.dumps(args))

    assert out["ok"] is True, out
    result = out["result"]
    assert result["watch_list_id"] == watch_list_id
    assert result["pending_job_id"] is not None
    assert result["message"]
    assert _contracts_sync_job_count(db_session) == before + 1
    rows = db_session.execute(select(WatchListInstrument).where(WatchListInstrument.watch_list_id == watch_list_id)).scalars().all()
    assert rows == []


def test_add_watch_list_instrument_still_adds_a_known_contract(db_session: Session) -> None:
    make_contract(db_session, con_id=CON_KNOWN, symbol=KNOWN_SYMBOL, local_symbol="ZZKNOWNK6")
    created = tradebot_agent._execute_tool_call(db_session, "", "create_watch_list", json.dumps({"name": "Core"}))
    watch_list_id = created["result"]["id"]

    args = {"watch_list_id": watch_list_id, "symbol": KNOWN_SYMBOL, "sec_type": "FUT"}
    out = tradebot_agent._execute_tool_call(db_session, "add it", "add_watch_list_instrument", json.dumps(args))

    assert out["ok"] is True, out
    assert out["result"]["con_id"] == CON_KNOWN
    assert out["result"]["already_existed"] is False
    assert "pending_job_id" not in out["result"]
