"""Group instrument derivation and the instrument pattern filter (U2)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import TradeGroup
from src.services.trade_group_instruments import (
    InstrumentPatternError,
    instrument_filter_condition,
    trade_group_instruments,
    validate_instrument_pattern,
)
from tests.trade_group_factories import (
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_contract,
    make_exec_id,
    make_execution,
    make_group,
)


def _matching_group_names(session: Session, pattern: str, limit: int | None = None) -> list[str]:
    stmt = select(TradeGroup.name).where(instrument_filter_condition(pattern)).order_by(TradeGroup.name.asc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.execute(stmt).scalars().all())


# --------------------------------------------------------------------------
# Instrument derivation (KTD4)
# --------------------------------------------------------------------------


def test_instruments_resolve_from_the_contracts_security_master(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL campaign", account.id)
    make_contract(db_session, con_id=CON_CL, symbol="CL")
    # raw carries a different symbol so we can prove contracts won.
    make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(10000001), raw_symbol="WRONG")

    assert trade_group_instruments(db_session, [group.id]) == {group.id: ["CL"]}


def test_instruments_fall_back_to_the_raw_contract_symbol(db_session: Session) -> None:
    """Many traded option con_ids never reach the security master."""
    account = make_account(db_session)
    group = make_group(db_session, "NG campaign", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_NG, exec_id=make_exec_id(10000002), raw_symbol="NG")

    assert trade_group_instruments(db_session, [group.id]) == {group.id: ["NG"]}


def test_instruments_dedupe_the_union_of_both_sources(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL + NG", account.id)
    make_contract(db_session, con_id=CON_CL, symbol="CL")
    make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(10000003), raw_symbol="CL")
    make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(10000004), raw_symbol="CL")
    make_execution(db_session, group=group, account=account, con_id=CON_NG, exec_id=make_exec_id(10000005), raw_symbol="NG")

    assert trade_group_instruments(db_session, [group.id]) == {group.id: ["CL", "NG"]}


def test_instruments_skip_executions_with_no_resolvable_symbol(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "unknown instrument", account.id)
    make_execution(db_session, group=group, account=account, con_id=None, exec_id=make_exec_id(10000006), raw_symbol=None)

    assert trade_group_instruments(db_session, [group.id]) == {group.id: []}


def test_instruments_returns_an_entry_for_every_requested_group(db_session: Session) -> None:
    account = make_account(db_session)
    with_fills = make_group(db_session, "CL campaign", account.id)
    without_fills = make_group(db_session, "no fills yet", account.id)
    make_execution(db_session, group=with_fills, account=account, con_id=CON_CL, exec_id=make_exec_id(10000007), raw_symbol="CL")

    result = trade_group_instruments(db_session, [with_fills.id, without_fills.id])

    assert result == {with_fills.id: ["CL"], without_fills.id: []}


def test_instruments_with_no_group_ids_is_empty(db_session: Session) -> None:
    assert trade_group_instruments(db_session, []) == {}


# --------------------------------------------------------------------------
# The pattern filter (KTD5)
# --------------------------------------------------------------------------


@pytest.fixture
def book(db_session: Session):
    """Three groups: CL (via contracts), NG (via raw), ES (name only, no fills)."""
    account = make_account(db_session)
    cl = make_group(db_session, "Crude campaign", account.id)
    ng = make_group(db_session, "Gas campaign", account.id)
    es_by_name = make_group(db_session, "ES index hedge", account.id)
    make_contract(db_session, con_id=CON_CL, symbol="CL")
    make_execution(db_session, group=cl, account=account, con_id=CON_CL, exec_id=make_exec_id(20000001), raw_symbol="CL")
    make_execution(db_session, group=ng, account=account, con_id=CON_NG, exec_id=make_exec_id(20000002), raw_symbol="NG")
    db_session.flush()
    return {"account": account, "cl": cl, "ng": ng, "es": es_by_name}


def test_pattern_matches_the_groups_instruments(db_session: Session, book) -> None:
    assert _matching_group_names(db_session, "CL.*") == ["Crude campaign"]


def test_pattern_that_matches_nothing_returns_nothing(db_session: Session, book) -> None:
    assert _matching_group_names(db_session, "ZC") == []


def test_alternation_matches_either_instrument(db_session: Session, book) -> None:
    assert _matching_group_names(db_session, "CL|NG") == ["Crude campaign", "Gas campaign"]


def test_group_name_is_the_fallback_when_instruments_do_not_resolve(db_session: Session, book) -> None:
    """``ES index hedge`` has no fills at all, so only its name can match."""
    assert _matching_group_names(db_session, "ES") == ["ES index hedge"]


def test_matching_is_case_insensitive_in_both_directions(db_session: Session, book) -> None:
    assert _matching_group_names(db_session, "cl.*") == ["Crude campaign"]
    assert _matching_group_names(db_session, "CRUDE") == ["Crude campaign"]


def test_pattern_matches_the_raw_symbol_fallback(db_session: Session, book) -> None:
    """The NG group's symbol exists only in the execution's raw payload."""
    assert _matching_group_names(db_session, "^NG$") == ["Gas campaign"]


def test_filter_applies_before_the_limit_not_after(db_session: Session) -> None:
    """R10: a limit must trim matching rows, never leave the page empty.

    Ten groups, the two CL ones ordered last by name — filtering after a
    ``LIMIT 2`` would return zero rows.
    """
    account = make_account(db_session)
    for index in range(8):
        decoy = make_group(db_session, f"AAA decoy {index}", account.id)
        make_execution(db_session, group=decoy, account=account, con_id=CON_ES + index, exec_id=make_exec_id(3000 * 10000 + index), raw_symbol="ES")
    for index in range(2):
        target = make_group(db_session, f"ZZZ crude {index}", account.id)
        make_execution(db_session, group=target, account=account, con_id=CON_CL + index, exec_id=make_exec_id(3100 * 10000 + index), raw_symbol="CL")
    db_session.flush()

    assert _matching_group_names(db_session, "CL", limit=2) == ["ZZZ crude 0", "ZZZ crude 1"]


def test_group_with_no_executions_does_not_match_an_instrument_pattern(db_session: Session, book) -> None:
    """The name fallback must not turn into a match-everything."""
    assert "ES index hedge" not in _matching_group_names(db_session, "CL.*")


# --------------------------------------------------------------------------
# Pattern validation (400, not 500)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", ["CL[", "CL(", "*CL", "CL{2,1}"])
def test_malformed_pattern_raises_before_reaching_the_database(pattern: str) -> None:
    with pytest.raises(InstrumentPatternError):
        validate_instrument_pattern(pattern)


def test_blank_pattern_is_rejected(db_session: Session) -> None:
    for pattern in ("", "   "):
        with pytest.raises(InstrumentPatternError):
            validate_instrument_pattern(pattern)


def test_valid_patterns_round_trip_unchanged(db_session: Session) -> None:
    for pattern in ("CL", "CL.*", "CL|NG", "^ES$"):
        assert validate_instrument_pattern(pattern) == pattern


def test_filter_condition_validates_its_pattern(db_session: Session) -> None:
    """The condition builder is the one seam the router calls, so it validates too."""
    with pytest.raises(InstrumentPatternError):
        instrument_filter_condition("CL[")


def test_instruments_can_be_scoped_to_one_account(db_session: Session) -> None:
    """A cross-account group lists only what it holds in the filtered account."""
    main = make_account(db_session)
    lsc = make_account(db_session, "U7654321", "lsc")
    group = make_group(db_session, "Both accounts", lsc.id)
    make_execution(db_session, group=group, account=main, con_id=CON_CL, exec_id=make_exec_id(70000001), raw_symbol="CL")
    make_execution(db_session, group=group, account=lsc, con_id=CON_NG, exec_id=make_exec_id(70000002), raw_symbol="NG")

    assert trade_group_instruments(db_session, [group.id]) == {group.id: ["CL", "NG"]}
    assert trade_group_instruments(db_session, [group.id], main.id) == {group.id: ["CL"]}
    assert trade_group_instruments(db_session, [group.id], lsc.id) == {group.id: ["NG"]}
