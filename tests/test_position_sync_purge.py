"""Settled-wins purge of the live TWS position overlay.

``_purge_superseded_live_positions`` is what lets the overlay expire without a
TWS connection: the settled FlexQuery import is the trigger. This is the
destructive half of the fix, so the guards that keep a genuinely-held position
from being deleted matter as much as the disposal itself.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from src.models import LivePosition
from src.services.position_sync_flexquery import _purge_superseded_live_positions
from tests.trade_group_factories import (
    ACCOUNT_LSC,
    CON_CL,
    CON_NG,
    make_account,
    make_exec_id,
    make_execution,
    make_live_position,
)

UTC = timezone.utc
AS_OF = date(2025, 1, 15)
CAPTURE_BEFORE = datetime(2025, 1, 13, 23, 9, tzinfo=UTC)
CAPTURE_ON_AS_OF = datetime(2025, 1, 15, 18, 30, tzinfo=UTC)


def _live_con_ids(session, account_id: int) -> set[int]:
    return set(session.execute(select(LivePosition.con_id).where(LivePosition.account_id == account_id)).scalars().all())


def _round_trip(session, account, con_id, *, seq: int, closed_at: datetime) -> None:
    """A buy then an equal sell -- signed quantities netting to zero."""
    make_execution(
        session,
        group=None,
        account=account,
        con_id=con_id,
        exec_id=make_exec_id(seq),
        quantity=1.0,
        executed_at=closed_at - timedelta(days=3),
    )
    make_execution(
        session,
        group=None,
        account=account,
        con_id=con_id,
        exec_id=make_exec_id(seq + 1),
        side="SELL",
        quantity=-1.0,
        executed_at=closed_at,
    )


def test_watermark_purges_a_capture_predating_the_snapshot(db_session):
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=CAPTURE_BEFORE)

    assert _purge_superseded_live_positions(db_session, account.id, AS_OF) == 1
    assert _live_con_ids(db_session, account.id) == set()


def test_watermark_spares_a_capture_on_the_snapshot_date_and_a_missing_as_of(db_session):
    """Strict '>' (an overnight capture owns the next trade date), plus the
    guard for a report with no resolvable reportDate."""
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=CAPTURE_ON_AS_OF)
    make_live_position(db_session, account=account, con_id=CON_NG, fetched_at=CAPTURE_BEFORE)

    assert _purge_superseded_live_positions(db_session, account.id, None) == 0
    assert _purge_superseded_live_positions(db_session, account.id, AS_OF) == 1
    assert _live_con_ids(db_session, account.id) == {CON_CL}


def test_purge_is_scoped_to_the_synced_account(db_session):
    main = make_account(db_session)
    other = make_account(db_session, account=ACCOUNT_LSC, alias="second")
    make_live_position(db_session, account=main, con_id=CON_CL, fetched_at=CAPTURE_BEFORE)
    make_live_position(db_session, account=other, con_id=CON_CL, fetched_at=CAPTURE_BEFORE)

    assert _purge_superseded_live_positions(db_session, main.id, AS_OF) == 1
    assert _live_con_ids(db_session, other.id) == {CON_CL}, "other account untouched"


def test_net_zero_fills_clear_a_close_the_watermark_has_not_reached(db_session):
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=CAPTURE_ON_AS_OF)
    _round_trip(db_session, account, CON_CL, seq=1, closed_at=CAPTURE_ON_AS_OF + timedelta(hours=2))

    assert _purge_superseded_live_positions(db_session, account.id, AS_OF) == 1, "the fill signal must fire here"
    assert _live_con_ids(db_session, account.id) == set()


def test_instrument_with_no_fills_survives(db_session):
    """The load-bearing guard: an empty fill history means transferred-in lots
    or fills predating the sync window, not a close."""
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_NG, fetched_at=CAPTURE_ON_AS_OF)

    assert _purge_superseded_live_positions(db_session, account.id, AS_OF) == 0
    assert _live_con_ids(db_session, account.id) == {CON_NG}


def test_non_canonical_fills_do_not_net_a_held_position_flat(db_session):
    account = make_account(db_session)
    make_live_position(db_session, account=account, con_id=CON_CL, fetched_at=CAPTURE_ON_AS_OF)
    make_execution(
        db_session,
        group=None,
        account=account,
        con_id=CON_CL,
        exec_id=make_exec_id(30),
        quantity=1.0,
        executed_at=CAPTURE_ON_AS_OF + timedelta(hours=1),
    )
    make_execution(
        db_session,
        group=None,
        account=account,
        con_id=CON_CL,
        exec_id=make_exec_id(31),
        side="SELL",
        quantity=-1.0,
        executed_at=CAPTURE_ON_AS_OF + timedelta(hours=2),
        is_canonical=False,
    )

    assert _purge_superseded_live_positions(db_session, account.id, AS_OF) == 0
    assert _live_con_ids(db_session, account.id) == {CON_CL}
