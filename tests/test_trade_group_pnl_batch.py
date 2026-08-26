"""Batched multi-group trade-group P&L with the intraday overlay (U1).

The load-bearing assertion is the equivalence test: the batch function must
agree with ``compute_trade_group_pnl`` field for field. A slicing bug in the
batch path produces numbers that still look like money, so nothing but a direct
comparison catches it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from src.models import ContractRef
from src.services.trade_group_pnl import (
    compute_trade_group_pnl,
    trade_group_batch_pnls,
    trade_group_total_pnls,
)
from tests.trade_group_factories import (
    ACCOUNT_LSC,
    ACCOUNT_THIRD,
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
    make_live_position,
    make_position,
    make_quote,
    now,
)


def _batch_one(session: Session, group_id: int, **kwargs: Any):
    return trade_group_batch_pnls(session, [group_id], **kwargs)[group_id]


# --------------------------------------------------------------------------
# Equivalence with the per-group path (R6)
# --------------------------------------------------------------------------


def test_batch_matches_compute_trade_group_pnl_field_by_field(db_session: Session) -> None:
    """The batch figures equal the single-group figures for the same group."""
    account = make_account(db_session)
    group = make_group(db_session, "CL Dec'27 Short Gamma", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=1_500.0, exec_id=make_exec_id(12345678))
    make_position(db_session, account=account, con_id=CON_CL)
    make_live_position(db_session, account=account, con_id=CON_CL)
    make_quote(db_session, CON_CL, mark=73.0)
    make_live_execution(db_session, account=account, con_id=CON_CL, exec_id=make_exec_id(12345679))

    single = compute_trade_group_pnl(db_session, group.id)
    batched = _batch_one(db_session, group.id)

    assert batched.realized_pnl == single.realized_pnl
    assert batched.settled_unrealized_pnl == single.settled_unrealized_pnl
    assert batched.intraday_unrealized_pnl == single.intraday_unrealized_pnl
    assert batched.intraday_realized_pnl == single.intraday_realized_pnl
    assert batched.intraday_total_pnl == single.intraday_total_pnl
    assert batched.marks_as_of == single.marks_as_of
    # Not a vacuous comparison — the overlay actually produced numbers.
    assert batched.intraday_unrealized_pnl is not None
    assert batched.intraday_realized_pnl is not None


def test_batch_matches_per_group_path_across_several_groups(db_session: Session) -> None:
    """Every group in a multi-group call agrees with its own single-group call."""
    main = make_account(db_session)
    lsc = make_account(db_session, ACCOUNT_LSC, "lsc")
    open_group = make_group(db_session, "CL open", main.id)
    closed_group = make_group(db_session, "NG round trip", main.id)
    cross_group = make_group(db_session, "ES other account", lsc.id)
    empty_group = make_group(db_session, "no fills yet", main.id)

    make_execution(db_session, group=open_group, account=main, con_id=CON_CL, realized=100.0, exec_id=make_exec_id(11111111))
    make_execution(db_session, group=closed_group, account=main, con_id=CON_NG, realized=-250.0, exec_id=make_exec_id(22222222), raw_symbol="NG")
    make_execution(db_session, group=cross_group, account=lsc, con_id=CON_ES, realized=42.0, exec_id=make_exec_id(33333333), raw_symbol="ES")
    make_position(db_session, account=main, con_id=CON_CL)
    make_position(db_session, account=lsc, con_id=CON_ES, unrealized=-500.0)
    make_live_position(db_session, account=main, con_id=CON_CL)
    make_quote(db_session, CON_CL, mark=71.5)

    ids = [open_group.id, closed_group.id, cross_group.id, empty_group.id]
    batched = trade_group_batch_pnls(db_session, ids)

    for group_id in ids:
        single = compute_trade_group_pnl(db_session, group_id)
        row = batched[group_id]
        assert row.realized_pnl == single.realized_pnl, group_id
        assert row.settled_unrealized_pnl == single.settled_unrealized_pnl, group_id
        assert row.intraday_unrealized_pnl == single.intraday_unrealized_pnl, group_id
        assert row.intraday_realized_pnl == single.intraday_realized_pnl, group_id
        assert row.intraday_total_pnl == single.intraday_total_pnl, group_id
        assert row.marks_as_of == single.marks_as_of, group_id


# --------------------------------------------------------------------------
# Attribution and slicing
# --------------------------------------------------------------------------


def test_shared_position_is_counted_in_full_for_both_groups(db_session: Session) -> None:
    """Attribution is intentionally non-additive: no split across groups."""
    account = make_account(db_session)
    first = make_group(db_session, "CL campaign A", account.id)
    second = make_group(db_session, "CL campaign B", account.id)
    make_execution(db_session, group=first, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(44444444))
    make_execution(db_session, group=second, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(55555555))
    make_position(db_session, account=account, con_id=CON_CL, unrealized=2_000.0)

    batched = trade_group_batch_pnls(db_session, [first.id, second.id])

    assert batched[first.id].settled_unrealized_pnl == 2_000.0
    assert batched[second.id].settled_unrealized_pnl == 2_000.0


def test_live_realized_is_deduped_against_that_groups_settled_ids(db_session: Session) -> None:
    """``settled_exec_ids`` is per group, never the union across groups.

    A live fill already settled *for this group* is dropped; the same fill must
    still count for a group that has not settled it.
    """
    account = make_account(db_session)
    settled_group = make_group(db_session, "CL settled", account.id)
    unsettled_group = make_group(db_session, "CL unsettled", account.id)
    shared_exec_id = make_exec_id(66666666)
    # settled_group owns the settled copy of the shared fill...
    make_execution(db_session, group=settled_group, account=account, con_id=CON_CL, realized=300.0, exec_id=shared_exec_id)
    # ...unsettled_group touches the same con_id via a different settled fill.
    make_execution(db_session, group=unsettled_group, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(77777777))
    make_position(db_session, account=account, con_id=CON_CL, unrealized=0.0)
    make_live_execution(db_session, account=account, con_id=CON_CL, exec_id=shared_exec_id, realized=300.0)

    batched = trade_group_batch_pnls(db_session, [settled_group.id, unsettled_group.id])

    # Settled wins for the group that has it: realized counted once, not twice.
    assert batched[settled_group.id].intraday_realized_pnl == 300.0
    # The other group has not settled that fill, so the live copy still counts.
    assert batched[unsettled_group.id].intraday_realized_pnl == 300.0


def test_closed_round_trip_reports_realized_without_settled_unrealized(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "NG closed", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_NG, realized=-750.0, exec_id=make_exec_id(88888888), raw_symbol="NG")

    row = _batch_one(db_session, group.id)

    assert row.realized_pnl == -750.0
    assert row.settled_unrealized_pnl is None


def test_group_with_no_executions_reports_none_not_zero(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "empty", account.id)

    row = _batch_one(db_session, group.id)

    assert row.realized_pnl is None
    assert row.settled_unrealized_pnl is None
    assert row.intraday_unrealized_pnl is None
    assert row.intraday_realized_pnl is None
    assert row.intraday_total_pnl is None
    assert row.marks_as_of is None
    assert row.live_is_stale is False


def test_combo_summary_realized_is_used_over_leg_sum(db_session: Session) -> None:
    """The combo-aware rule survives the batch path (not a sum over legs)."""
    account = make_account(db_session)
    group = make_group(db_session, "CL spread", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=900.0, exec_id=make_exec_id(99999999), exec_role="combo_summary")
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=400.0, exec_id=make_exec_id(99999999, 2), exec_role="leg")
    make_execution(db_session, group=group, account=account, con_id=CON_NG, realized=500.0, exec_id=make_exec_id(99999999, 3), exec_role="leg", raw_symbol="NG")

    row = _batch_one(db_session, group.id)

    assert row.realized_pnl == 900.0


# --------------------------------------------------------------------------
# Graceful degradation and staleness
# --------------------------------------------------------------------------


def test_without_live_rows_intraday_equals_settled(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL settled only", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=100.0, exec_id=make_exec_id(10101010))
    make_position(db_session, account=account, con_id=CON_CL, unrealized=2_000.0)

    row = _batch_one(db_session, group.id)

    assert row.intraday_unrealized_pnl == row.settled_unrealized_pnl == 2_000.0
    assert row.intraday_realized_pnl == row.realized_pnl == 100.0
    assert row.marks_as_of is None
    assert row.live_is_stale is False


def _stale_pair(session: Session, account: Account, con_id: int) -> None:
    """A live snapshot from a prior MT day with a newer settled import behind it."""
    yesterday = now() - timedelta(days=1)
    make_live_position(session, account=account, con_id=con_id, fetched_at=yesterday)
    make_position(session, account=account, con_id=con_id, fetched_at=now(), unrealized=1_000.0)
    make_quote(session, con_id)


def _fresh_pair(session: Session, account: Account, con_id: int) -> None:
    make_live_position(session, account=account, con_id=con_id, fetched_at=now())
    make_position(session, account=account, con_id=con_id, fetched_at=now(), unrealized=1_000.0)
    make_quote(session, con_id)


def test_staleness_flag_false_when_every_live_view_is_fresh(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL fresh", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(12121212))
    _fresh_pair(db_session, account, CON_CL)

    assert _batch_one(db_session, group.id).live_is_stale is False


def test_staleness_flag_false_when_live_views_are_mixed(db_session: Session) -> None:
    """One stale leg among fresh ones does not flag the whole row."""
    account = make_account(db_session)
    group = make_group(db_session, "CL mixed", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(13131313))
    make_execution(db_session, group=group, account=account, con_id=CON_NG, realized=None, exec_id=make_exec_id(13131313, 2), raw_symbol="NG")
    _fresh_pair(db_session, account, CON_CL)
    _stale_pair(db_session, account, CON_NG)

    assert _batch_one(db_session, group.id).live_is_stale is False


def test_staleness_flag_true_only_when_every_live_view_is_stale(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL stale", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(14141414))
    make_execution(db_session, group=group, account=account, con_id=CON_NG, realized=None, exec_id=make_exec_id(14141414, 2), raw_symbol="NG")
    _stale_pair(db_session, account, CON_CL)
    _stale_pair(db_session, account, CON_NG)

    assert _batch_one(db_session, group.id).live_is_stale is True


# --------------------------------------------------------------------------
# Price magnifiers (shared loader)
# --------------------------------------------------------------------------


def test_price_magnifier_normalizes_the_live_mark(db_session: Session) -> None:
    """A cents-quoted product is normalized on the batch path too.

    Without the magnifier the live unrealized comes out 100x wrong — the exact
    failure mode of a magnifier fetch that lives in only one of the two paths.
    """
    account = make_account(db_session)
    group = make_group(db_session, "ZC cents-quoted", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=None, exec_id=make_exec_id(15151515))
    db_session.add(
        ContractRef(
            con_id=CON_CL,
            symbol="ZC",
            sec_type="FUT",
            exchange="CBOT",
            currency="USD",
            multiplier="5000",
            price_magnifier=100,
        )
    )
    db_session.flush()
    # Quoted in cents (450.0) against a dollar-denominated avg_cost.
    make_live_position(db_session, account=account, con_id=CON_CL, quantity=1.0, avg_cost=22_000.0, multiplier="5000")
    make_position(db_session, account=account, con_id=CON_CL, unrealized=0.0, multiplier="5000")
    make_quote(db_session, CON_CL, mark=450.0)

    row = _batch_one(db_session, group.id)

    # 1 * (450/100) * 5000 - 1 * 22000 = 500.0 (not 1 * 450 * 5000 - 22000).
    assert row.intraday_unrealized_pnl == 500.0


# --------------------------------------------------------------------------
# Query count (KTD1)
# --------------------------------------------------------------------------


def _count_statements(session: Session, fn) -> int:
    counter = {"n": 0}

    def _on_execute(*_args: Any, **_kwargs: Any) -> None:
        counter["n"] += 1

    event.listen(session.get_bind(), "before_cursor_execute", _on_execute)
    try:
        fn()
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", _on_execute)
    return counter["n"]


def test_query_count_does_not_grow_with_group_count(db_session: Session) -> None:
    account = make_account(db_session)
    groups = []
    for index in range(10):
        group = make_group(db_session, f"CL campaign {index}", account.id)
        make_execution(
            db_session,
            group=group,
            account=account,
            con_id=CON_CL + index,
            realized=float(index),
            exec_id=make_exec_id(2020 * 10000 + index),
        )
        make_position(db_session, account=account, con_id=CON_CL + index, unrealized=100.0)
        groups.append(group)
    db_session.flush()

    one = _count_statements(db_session, lambda: trade_group_batch_pnls(db_session, [groups[0].id]))
    ten = _count_statements(db_session, lambda: trade_group_batch_pnls(db_session, [g.id for g in groups]))

    assert one == ten, f"query count grew with group count: {one} -> {ten}"


def test_settled_only_mode_skips_the_overlay_queries(db_session: Session) -> None:
    """``include_intraday=False`` is cheaper than the overlay path (R15/KTD2)."""
    account = make_account(db_session)
    group = make_group(db_session, "CL settled only", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=100.0, exec_id=make_exec_id(16161616))
    make_position(db_session, account=account, con_id=CON_CL, unrealized=2_000.0)
    db_session.flush()

    settled = _count_statements(db_session, lambda: trade_group_batch_pnls(db_session, [group.id], include_intraday=False))
    overlay = _count_statements(db_session, lambda: trade_group_batch_pnls(db_session, [group.id], include_intraday=True))

    assert settled < overlay
    row = trade_group_batch_pnls(db_session, [group.id], include_intraday=False)[group.id]
    assert row.settled_unrealized_pnl == 2_000.0
    assert row.intraday_unrealized_pnl is None
    assert row.marks_as_of is None


# --------------------------------------------------------------------------
# The existing settled-total wrapper keeps its contract (KTD3)
# --------------------------------------------------------------------------


def test_total_pnls_wrapper_keeps_its_settled_meaning_and_cost(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "CL total", account.id)
    empty = make_group(db_session, "CL empty", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, realized=1_500.0, exec_id=make_exec_id(17171717))
    make_position(db_session, account=account, con_id=CON_CL, unrealized=2_000.0)
    # A live row that would move the number if the wrapper leaked the overlay.
    make_live_position(db_session, account=account, con_id=CON_CL, avg_cost=1.0)
    make_quote(db_session, CON_CL, mark=999.0)
    db_session.flush()

    totals = trade_group_total_pnls(db_session, [group.id, empty.id])

    assert totals[group.id] == 3_500.0  # settled realized + settled unrealized
    assert totals[empty.id] is None
    assert _count_statements(db_session, lambda: trade_group_total_pnls(db_session, [group.id, empty.id])) == 2


def test_total_pnls_empty_group_ids_returns_empty(db_session: Session) -> None:
    assert trade_group_total_pnls(db_session, []) == {}
    assert trade_group_batch_pnls(db_session, []) == {}


# --------------------------------------------------------------------------
# Account scoping (groups are cross-account by design)
# --------------------------------------------------------------------------


def _cross_account_group(session: Session):
    """One group holding legs in two accounts — the V1 cross-account case."""
    main = make_account(session)
    lsc = make_account(session, ACCOUNT_LSC, "lsc")
    group = make_group(session, "CL across both accounts", lsc.id)
    make_execution(session, group=group, account=main, con_id=CON_CL, realized=1_000.0, exec_id=make_exec_id(60000001))
    make_execution(session, group=group, account=lsc, con_id=CON_NG, realized=-250.0, exec_id=make_exec_id(60000002), raw_symbol="NG")
    make_position(session, account=main, con_id=CON_CL, unrealized=5_000.0)
    make_position(session, account=lsc, con_id=CON_NG, unrealized=-400.0)
    session.flush()
    return group, main, lsc


def test_unscoped_batch_totals_every_account(db_session: Session) -> None:
    group, _main, _lsc = _cross_account_group(db_session)

    row = _batch_one(db_session, group.id)

    assert row.realized_pnl == 750.0
    assert row.settled_unrealized_pnl == 4_600.0


def test_account_scoped_batch_reports_only_that_accounts_legs(db_session: Session) -> None:
    """Filtering to an account must move the numbers, not just the row list."""
    group, main, lsc = _cross_account_group(db_session)

    main_row = trade_group_batch_pnls(db_session, [group.id], account_id=main.id)[group.id]
    lsc_row = trade_group_batch_pnls(db_session, [group.id], account_id=lsc.id)[group.id]

    assert main_row.realized_pnl == 1_000.0
    assert main_row.settled_unrealized_pnl == 5_000.0
    assert lsc_row.realized_pnl == -250.0
    assert lsc_row.settled_unrealized_pnl == -400.0
    # And the two accounts' slices reconcile to the unscoped totals.
    assert main_row.realized_pnl + lsc_row.realized_pnl == _batch_one(db_session, group.id).realized_pnl


def test_account_scoping_applies_to_the_settled_only_path_too(db_session: Session) -> None:
    group, main, _lsc = _cross_account_group(db_session)

    assert trade_group_total_pnls(db_session, [group.id])[group.id] == 5_350.0
    assert trade_group_total_pnls(db_session, [group.id], account_id=main.id)[group.id] == 6_000.0


def test_account_with_no_legs_in_the_group_reports_nothing(db_session: Session) -> None:
    group, _main, _lsc = _cross_account_group(db_session)
    other = make_account(db_session, ACCOUNT_THIRD, "other")

    row = trade_group_batch_pnls(db_session, [group.id], account_id=other.id)[group.id]

    assert row.realized_pnl is None
    assert row.settled_unrealized_pnl is None
    assert row.intraday_total_pnl is None
