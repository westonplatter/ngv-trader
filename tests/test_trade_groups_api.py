"""`GET /trade-groups` with the P&L split, instruments, and pattern filter (U3)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.api.main import app
from tests.trade_group_factories import (
    ACCOUNT_LSC,
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_contract,
    make_exec_id,
    make_execution,
    make_group,
    make_live_position,
    make_position,
    make_quote,
)

BASE = "/api/v1/trade-groups"


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient whose requests run inside the test's rolled-back session."""
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def book(db_session: Session):
    """Two accounts, four groups: CL open, NG open, ES closed, and an empty one."""
    main = make_account(db_session)
    lsc = make_account(db_session, ACCOUNT_LSC, "lsc")

    crude = make_group(db_session, "Crude campaign", main.id)
    make_contract(db_session, con_id=CON_CL, symbol="CL")
    make_execution(db_session, group=crude, account=main, con_id=CON_CL, realized=1_500.0, exec_id=make_exec_id(40000001), raw_symbol="CL")
    make_position(db_session, account=main, con_id=CON_CL, unrealized=2_000.0)
    make_live_position(db_session, account=main, con_id=CON_CL)
    make_quote(db_session, CON_CL, mark=73.0)

    gas = make_group(db_session, "Gas campaign", lsc.id)
    make_execution(db_session, group=gas, account=lsc, con_id=CON_NG, realized=-250.0, exec_id=make_exec_id(40000002), raw_symbol="NG")

    index = make_group(db_session, "Index hedge", main.id, status="closed")
    make_execution(db_session, group=index, account=main, con_id=CON_ES, realized=42.0, exec_id=make_exec_id(40000003), raw_symbol="ES")

    empty = make_group(db_session, "No fills yet", main.id)
    db_session.flush()
    return {"main": main, "lsc": lsc, "crude": crude, "gas": gas, "index": index, "empty": empty}


def _by_name(rows: list[dict]) -> dict[str, dict]:
    return {row["name"]: row for row in rows}


# --------------------------------------------------------------------------
# Non-regression for existing consumers (R15)
# --------------------------------------------------------------------------


def test_default_request_leaves_every_new_field_unset(client: TestClient, book) -> None:
    """The Strategies left panel and the group picker see no change."""
    rows = _by_name(client.get(BASE).json())

    crude = rows["Crude campaign"]
    # The pre-existing settled Total PnL is unchanged: realized + settled unrealized.
    assert crude["total_pnl"] == 3_500.0
    assert crude["primary_strategy_value"] is None
    for field in (
        "realized_pnl",
        "unrealized_pnl",
        "intraday_unrealized_pnl",
        "intraday_realized_pnl",
        "intraday_total_pnl",
        "marks_as_of",
        "instruments",
    ):
        assert crude[field] is None, field
    assert crude["live_is_stale"] is False


def test_include_intraday_false_is_the_default(client: TestClient, book) -> None:
    assert client.get(BASE).json() == client.get(BASE, params={"include_intraday": "false"}).json()


# --------------------------------------------------------------------------
# The table's payload (R2, R3, R4, R5)
# --------------------------------------------------------------------------


def test_include_intraday_populates_the_split_and_the_marks_timestamp(client: TestClient, book) -> None:
    rows = _by_name(client.get(BASE, params={"include_intraday": "true"}).json())

    crude = rows["Crude campaign"]
    assert crude["realized_pnl"] == 1_500.0
    assert crude["unrealized_pnl"] == 2_000.0
    assert crude["intraday_unrealized_pnl"] is not None
    assert crude["intraday_realized_pnl"] == 1_500.0
    assert crude["intraday_total_pnl"] is not None
    assert crude["marks_as_of"] is not None
    # Total reconciles to Realized + Unrealized within the same layer.
    assert crude["intraday_total_pnl"] == pytest.approx(crude["intraday_unrealized_pnl"] + crude["intraday_realized_pnl"])


def test_a_group_without_live_data_degrades_to_settled_figures(client: TestClient, book) -> None:
    gas = _by_name(client.get(BASE, params={"include_intraday": "true"}).json())["Gas campaign"]

    assert gas["realized_pnl"] == -250.0
    assert gas["intraday_realized_pnl"] == -250.0
    assert gas["marks_as_of"] is None
    assert gas["live_is_stale"] is False


def test_instruments_are_returned_per_row_and_empty_never_null(client: TestClient, book) -> None:
    rows = _by_name(client.get(BASE, params={"include_intraday": "true"}).json())

    assert rows["Crude campaign"]["instruments"] == ["CL"]
    assert rows["Gas campaign"]["instruments"] == ["NG"]
    assert rows["No fills yet"]["instruments"] == []


def test_account_alias_filter_source_is_unchanged(client: TestClient, book) -> None:
    """Accounts are filtered by id; the UI resolves the alias from /accounts."""
    rows = client.get(BASE, params={"account_id": book["lsc"].id}).json()

    assert [row["name"] for row in rows] == ["Gas campaign"]


# --------------------------------------------------------------------------
# Filtering (R7, R8, R9, R10)
# --------------------------------------------------------------------------


def test_instrument_pattern_selects_only_matching_groups(client: TestClient, book) -> None:
    rows = client.get(BASE, params={"instrument": "CL.*"}).json()

    assert [row["name"] for row in rows] == ["Crude campaign"]


def test_instrument_and_account_filters_compose(client: TestClient, book) -> None:
    matching = client.get(BASE, params={"instrument": "NG", "account_id": book["lsc"].id}).json()
    conflicting = client.get(BASE, params={"instrument": "NG", "account_id": book["main"].id}).json()

    assert [row["name"] for row in matching] == ["Gas campaign"]
    assert conflicting == []


def test_status_open_excludes_closed_and_archived_groups(client: TestClient, book) -> None:
    names = [row["name"] for row in client.get(BASE, params={"status": "open"}).json()]

    assert "Index hedge" not in names
    assert {"Crude campaign", "Gas campaign", "No fills yet"} <= set(names)


def test_instrument_filter_populates_instruments_without_the_overlay(client: TestClient, book) -> None:
    """If you filtered by instrument you get to see which ones matched."""
    rows = client.get(BASE, params={"instrument": "CL.*"}).json()

    assert rows[0]["instruments"] == ["CL"]
    assert rows[0]["intraday_total_pnl"] is None


def test_malformed_instrument_pattern_is_a_400_not_a_500(client: TestClient, book) -> None:
    resp = client.get(BASE, params={"instrument": "CL["})

    assert resp.status_code == 400
    assert "CL[" in resp.json()["detail"]


def test_instrument_filter_applies_before_the_row_limit(client: TestClient, db_session: Session) -> None:
    """R10: with a limit of 2 and three matching groups among ten, two come back."""
    account = make_account(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        for index in range(7):
            decoy = make_group(db_session, f"Decoy {index}", account.id)
            make_execution(db_session, group=decoy, account=account, con_id=CON_ES + index, exec_id=make_exec_id(5000 * 10000 + index), raw_symbol="ES")
        for index in range(3):
            target = make_group(db_session, f"Crude {index}", account.id)
            make_execution(db_session, group=target, account=account, con_id=CON_CL + index, exec_id=make_exec_id(5100 * 10000 + index), raw_symbol="CL")
        db_session.flush()

        with TestClient(app) as test_client:
            rows = test_client.get(BASE, params={"instrument": "^CL$", "limit": 2}).json()
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert len(rows) == 2
    assert all(row["name"].startswith("Crude") for row in rows)


# --------------------------------------------------------------------------
# One source of truth (R6)
# --------------------------------------------------------------------------


def test_list_row_agrees_with_the_group_detail_endpoint(client: TestClient, book) -> None:
    """The table and the detail panel must never show different numbers."""
    listed = _by_name(client.get(BASE, params={"include_intraday": "true"}).json())

    for name in ("Crude campaign", "Gas campaign", "No fills yet"):
        row = listed[name]
        group_id = row["id"]
        detail = client.get(f"{BASE}/{group_id}/executions").json()
        assert row["realized_pnl"] == detail["total_realized_pnl"], name
        assert row["unrealized_pnl"] == detail["total_unrealized_pnl"], name
        assert row["intraday_unrealized_pnl"] == detail["intraday_unrealized_pnl"], name
        assert row["intraday_realized_pnl"] == detail["intraday_realized_pnl"], name
        assert row["intraday_total_pnl"] == detail["intraday_total_pnl"], name
        assert row["marks_as_of"] == detail["marks_as_of"], name


def test_account_filter_scopes_the_figures_not_just_the_row_list(client: TestClient, db_session: Session) -> None:
    """A cross-account group must not report book-wide totals under one account."""
    main = make_account(db_session)
    lsc = make_account(db_session, ACCOUNT_LSC, "lsc")
    group = make_group(db_session, "CL across both accounts", lsc.id)
    make_execution(db_session, group=group, account=main, con_id=CON_CL, realized=1_000.0, exec_id=make_exec_id(80000001), raw_symbol="CL")
    make_execution(db_session, group=group, account=lsc, con_id=CON_NG, realized=-250.0, exec_id=make_exec_id(80000002), raw_symbol="NG")
    make_position(db_session, account=main, con_id=CON_CL, unrealized=5_000.0)
    make_position(db_session, account=lsc, con_id=CON_NG, unrealized=-400.0)
    db_session.flush()

    params = {"include_intraday": "true", "status": "open"}
    unscoped = _by_name(client.get(BASE, params=params).json())["CL across both accounts"]
    scoped = _by_name(client.get(BASE, params={**params, "account_id": lsc.id}).json())["CL across both accounts"]

    assert unscoped["realized_pnl"] == 750.0
    assert unscoped["unrealized_pnl"] == 4_600.0
    assert unscoped["instruments"] == ["CL", "NG"]

    assert scoped["realized_pnl"] == -250.0
    assert scoped["unrealized_pnl"] == -400.0
    assert scoped["instruments"] == ["NG"]


def test_account_scoped_row_matches_the_detail_endpoints_per_account_breakdown(client: TestClient, db_session: Session) -> None:
    """R6 extended: the scoped row equals that account's slice on the panel."""
    main = make_account(db_session)
    lsc = make_account(db_session, ACCOUNT_LSC, "lsc")
    group = make_group(db_session, "Cross-account campaign", lsc.id)
    make_execution(db_session, group=group, account=main, con_id=CON_CL, realized=1_000.0, exec_id=make_exec_id(81000001), raw_symbol="CL")
    make_execution(db_session, group=group, account=lsc, con_id=CON_NG, realized=-250.0, exec_id=make_exec_id(81000002), raw_symbol="NG")
    make_position(db_session, account=main, con_id=CON_CL, unrealized=5_000.0)
    make_position(db_session, account=lsc, con_id=CON_NG, unrealized=-400.0)
    db_session.flush()

    detail = client.get(f"{BASE}/{group.id}/executions").json()
    panel = {row["account_id"]: row for row in detail["by_account"]}[lsc.id]
    row = _by_name(client.get(BASE, params={"include_intraday": "true", "account_id": lsc.id}).json())["Cross-account campaign"]

    assert row["realized_pnl"] == panel["realized_pnl"]
    assert row["unrealized_pnl"] == panel["unrealized_pnl"]
    assert row["intraday_total_pnl"] == panel["intraday_total_pnl"]


def test_account_filter_selects_rows_by_group_ownership_not_leg_membership(client: TestClient, db_session: Session) -> None:
    """Characterizes today's row-selection rule, which the figures do not share.

    ``account_id`` picks rows by ``trade_groups.account_id`` (the group's owning
    account, set from its first assigned fill). A group owned by one account but
    holding legs in another is therefore absent from the other account's view,
    even though it has real exposure there. Scoping the *figures* per account is
    what this change fixed; broadening row selection to leg membership is a
    separate product decision, so it is pinned here rather than left ambiguous.
    """
    main = make_account(db_session)
    lsc = make_account(db_session, ACCOUNT_LSC, "lsc")
    group = make_group(db_session, "Owned by lsc, legs in main", lsc.id)
    make_execution(db_session, group=group, account=main, con_id=CON_CL, realized=1_000.0, exec_id=make_exec_id(82000001), raw_symbol="CL")
    db_session.flush()

    under_owner = client.get(BASE, params={"account_id": lsc.id}).json()
    under_leg_account = client.get(BASE, params={"account_id": main.id}).json()

    assert [r["name"] for r in under_owner] == ["Owned by lsc, legs in main"]
    assert under_leg_account == []
