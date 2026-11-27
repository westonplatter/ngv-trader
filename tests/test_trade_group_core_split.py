"""Core vs incremental split of a trade group's cost and realized P&L."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from src.domain.enums import ExecRole
from src.services.intraday_overlay import OverlaySource, PositionView, overlay_totals
from src.services.trade_group_pnl import (
    CoreSplit,
    GroupLedger,
    GroupOverlay,
    PairKey,
    core_split,
    load_group_ledgers,
    overlay_for_ledgers,
)
from tests.trade_group_factories import (
    CON_CL,
    CON_ES,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_group,
    make_live_execution,
    make_position,
)

ACCT = 1
LEAP, SHORT_CLOSED, SHORT_OPEN = 101, 102, 103
MAR_PUT, JUN_PUT = 201, 202
DEC28, DEC26, JAN27 = 301, 302, 303
ES_FUT, SHORT_PUT = 401, 402
LONG_PUT, INC_FUT, INC_FUT_CLOSED = 501, 502, 503


def _view(con_id: int, position: float, avg_cost: float, sec_type: str = "OPT") -> PositionView:
    return PositionView(
        account_id=ACCT,
        con_id=con_id,
        symbol="XYZ",
        local_symbol=None,
        sec_type=sec_type,
        multiplier="100",
        right=None,
        strike=None,
        position=position,
        avg_cost=avg_cost,
        mark=None,
        mark_ts=None,
        source=OverlaySource.SETTLED,
        live_unrealized=None,
        settled_mark_price=None,
        settled_unrealized=None,
        settled_position_value=None,
        as_of_date=None,
    )


def _ex(seq: int, con_id: int | None, realized: float | None = None, role: str = ExecRole.STANDALONE) -> Any:
    raw = {} if realized is None else {"fifoPnlRealized": realized}
    return SimpleNamespace(account_id=ACCT, con_id=con_id, exec_role=role, raw=raw, ib_exec_id=make_exec_id(seq))


def _live(seq: int, con_id: int, realized: float | None) -> Any:
    return SimpleNamespace(
        account_id=ACCT, con_id=con_id, exec_role=ExecRole.STANDALONE, realized_pnl=realized, ib_exec_id=make_exec_id(seq), side="SELL", quantity=1.0
    )


def _split(
    views: list[PositionView],
    executions: list[Any],
    core: set[int],
    live: list[Any] | None = None,
    live_fills: list[Any] | None = None,
) -> CoreSplit | None:
    ledger = GroupLedger(executions=executions, live_fills=live_fills or [])
    live = live or []
    totals = overlay_totals([], views, live, ledger.settled_exec_ids, ledger.realized_pnl)
    overlay = GroupOverlay(
        views=views,
        flex_rows=[],
        live_rows=[],
        expiries={},
        realized_pnl=ledger.realized_pnl,
        totals=totals,
        by_account={},
        live_execs=live,
        live_is_stale=False,
    )
    return core_split(overlay, ledger, {(ACCT, con_id) for con_id in core})


def _approx(split: CoreSplit | None, core_cost: float, incremental_net: float) -> None:
    assert split is not None
    assert split.core_cost == pytest.approx(core_cost)
    assert split.incremental_net == pytest.approx(incremental_net)


def test_ae1_leap_financed_by_short_calls() -> None:
    views = [_view(LEAP, 1.0, 12_190.78), _view(SHORT_OPEN, -1.0, 79.95)]
    executions = [_ex(1, LEAP), _ex(2, SHORT_CLOSED), _ex(3, SHORT_CLOSED, 327.15), _ex(4, SHORT_OPEN)]
    _approx(_split(views, executions, {LEAP}), 12_190.78, 407.10)


def test_ae2_rolled_put_counts_untagged_sell_as_core() -> None:
    views = [_view(JUN_PUT, 1.0, 3_200.0)]
    executions = [_ex(1, MAR_PUT), _ex(2, MAR_PUT, -2_500.0), _ex(3, JUN_PUT)]
    _approx(_split(views, executions, {MAR_PUT, JUN_PUT}), 5_700.0, 0.0)


def test_ae3_calendar_combo_legs_core_and_roll_incremental() -> None:
    views = [_view(DEC28, 1.0, 12_190.78), _view(JAN27, -1.0, 900.0)]
    executions = [_ex(1, DEC28), _ex(2, DEC26), _ex(3, DEC26, 500.0), _ex(4, JAN27)]
    _approx(_split(views, executions, {DEC28, DEC26}), 11_690.78, 900.0)


def test_ae4_short_future_core_has_negative_cost() -> None:
    views = [_view(ES_FUT, -1.0, 300_000.0, "FUT"), _view(SHORT_PUT, -1.0, 3_000.0)]
    executions = [_ex(1, ES_FUT), _ex(2, SHORT_PUT)]
    _approx(_split(views, executions, {ES_FUT}), -300_000.0, 3_000.0)


@pytest.mark.parametrize("sec_type", ["FUT", "CONTFUT", "FUTURE"])
def test_ae5_open_incremental_future_adds_zero(sec_type: str) -> None:
    views = [_view(LONG_PUT, 1.0, 2_000.0), _view(INC_FUT, 1.0, 300_000.0, sec_type)]
    executions = [_ex(1, LONG_PUT), _ex(2, INC_FUT), _ex(3, INC_FUT_CLOSED), _ex(4, INC_FUT_CLOSED, 1_500.0)]
    _approx(_split(views, executions, {LONG_PUT}), 2_000.0, 1_500.0)


def test_open_incremental_stock_still_counts_basis() -> None:
    views = [_view(LONG_PUT, 1.0, 2_000.0), _view(INC_FUT, 100.0, 50.0, "STK")]
    _approx(_split(views, [_ex(1, LONG_PUT), _ex(2, INC_FUT)], {LONG_PUT}), 2_000.0, -5_000.0)


def test_ae6_no_core_pairs_returns_none() -> None:
    views = [_view(LEAP, 1.0, 12_190.78)]
    assert _split(views, [_ex(1, LEAP)], set()) is None


def test_core_pairs_outside_the_ledger_return_none() -> None:
    assert _split([_view(LEAP, 1.0, 12_190.78)], [_ex(1, LEAP)], {JUN_PUT}) is None


def test_zero_core_cost_returns_none() -> None:
    views = [_view(LEAP, 1.0, 500.0)]
    assert _split(views, [_ex(1, LEAP), _ex(2, MAR_PUT, 500.0)], {LEAP, MAR_PUT}) is None


def test_core_contract_opened_today_uses_live_view_basis() -> None:
    views = [_view(LEAP, 1.0, 4_000.0)]
    fill = _live(1, LEAP, None)
    _approx(_split(views, [], {LEAP}, live=[fill], live_fills=[fill]), 4_000.0, 0.0)


def test_unsettled_roll_matches_settled_roll() -> None:
    views = [_view(JUN_PUT, 1.0, 3_200.0)]
    buy_mar, buy_jun = _ex(1, MAR_PUT), _ex(2, JUN_PUT)
    settled = _split(views, [buy_mar, buy_jun, _ex(3, MAR_PUT, -2_500.0)], {MAR_PUT, JUN_PUT})
    sell_mar = _live(3, MAR_PUT, -2_500.0)
    unsettled = _split(views, [buy_mar, buy_jun], {MAR_PUT, JUN_PUT}, live=[sell_mar], live_fills=[sell_mar])
    _approx(settled, 5_700.0, 0.0)
    assert unsettled == settled


def test_live_fill_already_settled_counts_once() -> None:
    views = [_view(LEAP, 1.0, 4_000.0)]
    settled = _ex(1, LEAP, 100.0)
    duplicate = _live(1, LEAP, 100.0)
    _approx(_split(views, [settled], {LEAP}, live=[duplicate]), 3_900.0, 0.0)


def test_combo_summary_with_realized_the_legs_lack_returns_none() -> None:
    views = [_view(LEAP, 1.0, 4_000.0)]
    executions = [_ex(1, LEAP), _ex(2, None, 500.0, ExecRole.COMBO_SUMMARY)]
    assert _split(views, executions, {LEAP}) is None


def test_combo_summary_without_realized_does_not_break_reconciliation() -> None:
    views = [_view(LEAP, 1.0, 4_000.0)]
    executions = [_ex(1, LEAP, 100.0), _ex(2, None, None, ExecRole.COMBO_SUMMARY)]
    _approx(_split(views, executions, {LEAP}), 3_900.0, 0.0)


def _overlay_for(session: Session, group_id: int) -> tuple[GroupLedger, GroupOverlay]:
    ledger = load_group_ledgers(session, [group_id])[group_id]
    return ledger, overlay_for_ledgers(session, {group_id: ledger})[group_id]


def test_mixed_group_through_the_real_overlay_reconciles(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "mixed", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(1))
    make_execution(db_session, group=group, account=account, con_id=CON_NG, exec_id=make_exec_id(2), side="SELL", quantity=-1.0)
    make_execution(db_session, group=group, account=account, con_id=CON_ES, exec_id=make_exec_id(3), realized=300.0)
    make_position(db_session, account=account, con_id=CON_CL, quantity=1.0, avg_cost=70_000.0, multiplier="1", unrealized=None)
    short_option = make_position(db_session, account=account, con_id=CON_NG, quantity=-1.0, avg_cost=3_000.0, multiplier="1", unrealized=None)
    short_option.sec_type = "OPT"
    make_live_execution(db_session, account=account, con_id=CON_ES, exec_id=make_exec_id(4), realized=250.0, group=group)
    make_live_execution(db_session, account=account, con_id=CON_CL, exec_id=make_exec_id(5), realized=100.0)
    db_session.flush()

    ledger, overlay = _overlay_for(db_session, group.id)
    split = core_split(overlay, ledger, {(account.id, CON_CL)})

    assert overlay.totals.intraday_realized == pytest.approx(650.0)
    _approx(split, 70_000.0 - 100.0, 550.0 + 3_000.0)


def test_live_fill_settled_under_same_exec_id_counts_once_in_real_overlay(db_session: Session) -> None:
    account = make_account(db_session)
    group = make_group(db_session, "dedupe", account.id)
    make_execution(db_session, group=group, account=account, con_id=CON_CL, exec_id=make_exec_id(1), realized=100.0)
    make_position(db_session, account=account, con_id=CON_CL, quantity=1.0, avg_cost=70_000.0, multiplier="1", unrealized=None)
    make_live_execution(db_session, account=account, con_id=CON_CL, exec_id=make_exec_id(1), realized=100.0)

    ledger, overlay = _overlay_for(db_session, group.id)

    _approx(core_split(overlay, ledger, {(account.id, CON_CL)}), 70_000.0 - 100.0, 0.0)


def test_shared_contract_uses_only_this_groups_share(db_session: Session) -> None:
    account = make_account(db_session)
    group_a = make_group(db_session, "A", account.id)
    group_b = make_group(db_session, "B", account.id)
    make_execution(db_session, group=group_a, account=account, con_id=CON_CL, exec_id=make_exec_id(1))
    make_execution(db_session, group=group_b, account=account, con_id=CON_CL, exec_id=make_exec_id(2))
    make_position(db_session, account=account, con_id=CON_CL, quantity=2.0, avg_cost=70_000.0, multiplier="1", unrealized=None)
    core: set[PairKey] = {(account.id, CON_CL)}

    ledger, overlay = _overlay_for(db_session, group_a.id)

    _approx(core_split(overlay, ledger, core), 70_000.0, 0.0)
