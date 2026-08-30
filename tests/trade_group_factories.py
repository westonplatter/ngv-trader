"""Row builders for trade-group tests.

Anonymized IBKR shapes only — accounts, con_ids, and exec ids follow
``docs/ibkr-sample-data.md``. Symbols, prices, and quantities stay realistic.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from src.models import (
    Account,
    ContractRef,
    LatestQuote,
    LiveExecution,
    LivePosition,
    Position,
    Trade,
    TradeExecution,
    TradeGroup,
    TradeGroupExecution,
    TradeGroupLiveExecution,
)
from src.services.intraday_overlay import ct_date

UTC = timezone.utc

ACCOUNT_MAIN = "U1234567"
ACCOUNT_LSC = "U7654321"
ACCOUNT_THIRD = "U8675309"
CON_CL = 1000000001
CON_NG = 1000000002
CON_ES = 1000000003


def now() -> datetime:
    return datetime.now(UTC)


def make_exec_id(seq: int, rev: int = 1) -> str:
    """A unique, obviously-fabricated ``ib_exec_id`` for the anonymized base.

    Built at runtime rather than written as a literal so the shape stays the one
    in docs/ibkr-sample-data.md while every fixture still gets a distinct id —
    and so `scripts/ibkr_sensitive_data_check.py` has no near-miss literals to
    flag. Real ids never appear in this repo. ``rev`` varies the trailing
    revision segment, for the legs of one combo.
    """
    return f"0000abcd.{seq:08d}.01.{rev:02d}"


def make_account(session: Session, account: str = ACCOUNT_MAIN, alias: str = "main") -> Account:
    row = Account(account=account, alias=alias)
    session.add(row)
    session.flush()
    return row


def make_group(session: Session, name: str, account_id: int | None = None, status: str = "open") -> TradeGroup:
    row = TradeGroup(account_id=account_id, name=name, status=status, opened_at=now())
    session.add(row)
    session.flush()
    return row


def make_contract(  # noqa: PLR0913
    session: Session,
    *,
    con_id: int,
    symbol: str,
    sec_type: str = "FUT",
    local_symbol: str | None = None,
    multiplier: str = "1000",
    price_magnifier: int | None = None,
) -> ContractRef:
    row = ContractRef(
        con_id=con_id,
        symbol=symbol,
        sec_type=sec_type,
        exchange="NYMEX",
        currency="USD",
        local_symbol=local_symbol,
        multiplier=multiplier,
        price_magnifier=price_magnifier,
    )
    session.add(row)
    session.flush()
    return row


def make_execution(  # noqa: PLR0913
    session: Session,
    *,
    group: TradeGroup | None,
    account: Account,
    con_id: int | None,
    exec_id: str,
    realized: float | None = None,
    exec_role: str = "standalone",
    raw_symbol: str | None = "CL",
    side: str = "BUY",
    quantity: float = 1.0,
    executed_at: datetime | None = None,
    is_canonical: bool = True,
) -> TradeExecution:
    """One settled fill, optionally assigned to ``group``.

    ``raw`` mirrors the FlexQuery sync's synthesized payload: ``fifoPnlRealized``
    carries realized P&L and ``contract.symbol`` carries the *underlying* root
    (``CL``), not the OCC/local symbol.

    ``quantity`` is **signed** as it is in the database -- a sell is negative --
    so a round trip is written as ``+n`` then ``-n``. ``executed_at`` and
    ``is_canonical`` are exposed for tests that reason about fill history
    relative to a point in time.
    """
    trade = Trade(account_id=account.id, status="filled", total_quantity=1.0, data_source="flex")
    session.add(trade)
    session.flush()
    contract: dict[str, Any] = {"secType": "FUT"}
    if raw_symbol is not None:
        contract["symbol"] = raw_symbol
    raw: dict[str, Any] = {"contract": contract}
    if realized is not None:
        raw["fifoPnlRealized"] = realized
    execution = TradeExecution(
        trade_id=trade.id,
        account_id=account.id,
        ib_exec_id=exec_id,
        exec_id_base=exec_id.split(".")[0],
        exec_revision=1,
        con_id=con_id,
        exec_role=exec_role,
        executed_at=executed_at or now(),
        quantity=quantity,
        price=70.0,
        side=side,
        data_source="flex",
        is_canonical=is_canonical,
        raw=raw,
    )
    session.add(execution)
    session.flush()
    if group is not None:
        session.add(
            TradeGroupExecution(
                trade_group_id=group.id,
                trade_execution_id=execution.id,
                source="manual",
                created_by="test",
                assigned_at=now(),
            )
        )
        session.flush()
    return execution


def make_position(  # noqa: PLR0913
    session: Session,
    *,
    account: Account,
    con_id: int,
    quantity: float = 1.0,
    avg_cost: float = 70_000.0,
    mark_price: float = 72.0,
    unrealized: float | None = 2_000.0,
    fetched_at: datetime | None = None,
    multiplier: str = "1000",
    as_of_date: date | None = None,
) -> Position:
    captured_at = fetched_at or now()
    row = Position(
        account_id=account.id,
        con_id=con_id,
        symbol="CL",
        sec_type="FUT",
        multiplier=multiplier,
        position=quantity,
        avg_cost=avg_cost,
        mark_price=mark_price,
        position_value=quantity * mark_price * float(multiplier),
        fifo_pnl_unrealized=unrealized,
        data_source="flex",
        # The trade date the snapshot belongs to, on the same clock the
        # supersede comparison uses. date.today() would read the *process*
        # timezone: on a UTC machine after 00:00 UTC it dates the snapshot a
        # day ahead of its own capture, and a fresh overlay then looks
        # superseded by it.
        as_of_date=as_of_date or ct_date(captured_at),
        fetched_at=captured_at,
    )
    session.add(row)
    session.flush()
    return row


def make_live_position(  # noqa: PLR0913
    session: Session,
    *,
    account: Account,
    con_id: int,
    quantity: float = 1.0,
    avg_cost: float = 70_000.0,
    fetched_at: datetime | None = None,
    multiplier: str = "1000",
) -> LivePosition:
    row = LivePosition(
        account_id=account.id,
        con_id=con_id,
        symbol="CL",
        sec_type="FUT",
        multiplier=multiplier,
        position=quantity,
        avg_cost=avg_cost,
        fetched_at=fetched_at or now(),
    )
    session.add(row)
    session.flush()
    return row


def make_quote(session: Session, con_id: int, mark: float = 73.0) -> LatestQuote:
    row = LatestQuote(con_id=con_id, mark=mark, market_ts=now(), ingested_at=now())
    session.add(row)
    session.flush()
    return row


def make_live_execution(  # noqa: PLR0913
    session: Session,
    *,
    account: Account,
    con_id: int,
    exec_id: str,
    realized: float | None = 250.0,
    group: TradeGroup | None = None,
) -> LiveExecution:
    row = LiveExecution(
        ib_exec_id=exec_id,
        account_id=account.id,
        con_id=con_id,
        side="SELL",
        quantity=1.0,
        price=73.0,
        realized_pnl=realized,
        exec_time=now(),
        fetched_at=now(),
    )
    session.add(row)
    session.flush()
    if group is not None:
        session.add(
            TradeGroupLiveExecution(
                trade_group_id=group.id,
                ib_exec_id=exec_id,
                account_id=account.id,
                con_id=con_id,
                source="manual",
                created_by="test",
                assigned_at=now(),
            )
        )
        session.flush()
    return row
