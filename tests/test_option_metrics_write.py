"""A greeks fetch that comes back empty must not erase the greeks we already have.

``reqTickers`` is a snapshot, and IBKR's model-greeks tick often lands after the
snapshot ends, so coverage swings run to run — 32/37 on a morning run, 12/38 the
same evening. The write path used to upsert every held con_id unconditionally,
so an empty evening run overwrote the morning's good values with NULLs and
rerunning the job made the gap worse instead of better. These tests pin the rule
that a fetch only ever writes what it actually received.
"""

import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.dialects import postgresql

from src.services.option_metrics_sync_tws import _write_option_metrics

NOW = datetime(2026, 8, 25, 21, 23, tzinfo=timezone.utc)

GREEK_COLUMNS = {"iv", "delta", "gamma", "theta", "vega", "und_price"}


class _FakeSession:
    """Captures statements instead of talking to Postgres."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    def execute(self, statement: Any) -> None:
        self.statements.append(statement)


class _Greeks:
    def __init__(self, **fields: Any) -> None:
        for name, value in fields.items():
            setattr(self, name, value)


class _Ticker:
    def __init__(self, model_greeks: Any) -> None:
        self.modelGreeks = model_greeks


def _written_columns(statement: Any) -> set[str]:
    """Column names the insert binds, whether the bound value is NULL or not.

    Binding a column to NULL is the bug, so this deliberately does not filter on
    the value. The ``param_N`` binds come from the ON CONFLICT SET clause, which
    mirrors the same columns.
    """
    params = statement.compile(dialect=postgresql.dialect()).params
    return {name for name in params if not name.startswith("param_")}


def _full_greeks() -> _Greeks:
    return _Greeks(impliedVol=0.2525, delta=0.4644, gamma=0.00158, theta=-3.05, vega=3.96, undPrice=4712.0)


def test_ticker_without_model_greeks_writes_nothing() -> None:
    session = _FakeSession()

    written, skipped = _write_option_metrics(session, {123456789: _Ticker(None)}, NOW)

    assert (written, skipped) == (0, 1)
    assert session.statements == [], "an empty fetch must leave the stored row untouched"


def test_all_nan_greeks_are_treated_as_absent() -> None:
    """IBKR sends NaN sentinels rather than omitting the fields."""
    session = _FakeSession()
    nan_greeks = _Greeks(
        impliedVol=math.nan,
        delta=math.nan,
        gamma=math.nan,
        theta=math.nan,
        vega=math.nan,
        undPrice=math.nan,
    )

    written, skipped = _write_option_metrics(session, {123456789: _Ticker(nan_greeks)}, NOW)

    assert (written, skipped) == (0, 1)
    assert session.statements == []


def test_full_greeks_are_written() -> None:
    session = _FakeSession()

    written, skipped = _write_option_metrics(session, {234567890: _Ticker(_full_greeks())}, NOW)

    assert (written, skipped) == (1, 0)
    assert GREEK_COLUMNS <= _written_columns(session.statements[0])


def test_partial_greeks_write_only_what_arrived() -> None:
    """A missing field keeps its stored value rather than being NULLed."""
    session = _FakeSession()
    partial = _Greeks(impliedVol=0.2525, delta=0.4644, gamma=None, theta=None, vega=None, undPrice=None)

    written, skipped = _write_option_metrics(session, {234567890: _Ticker(partial)}, NOW)

    assert (written, skipped) == (1, 0)
    written_columns = _written_columns(session.statements[0])
    assert {"iv", "delta"} <= written_columns
    assert written_columns.isdisjoint({"gamma", "theta", "vega", "und_price"})


def test_timestamps_advance_only_for_rows_that_got_greeks() -> None:
    """A row's market_ts should date its values, not the last attempt."""
    session = _FakeSession()
    tickers = {123456789: _Ticker(None), 234567890: _Ticker(_full_greeks())}

    written, skipped = _write_option_metrics(session, tickers, NOW)

    assert (written, skipped) == (1, 1)
    assert len(session.statements) == 1
    assert {"market_ts", "ingested_at"} <= _written_columns(session.statements[0])


def test_one_empty_fetch_does_not_block_the_others() -> None:
    session = _FakeSession()
    tickers = {
        123456789: _Ticker(None),
        234567890: _Ticker(_full_greeks()),
        345678901: _Ticker(_full_greeks()),
    }

    written, skipped = _write_option_metrics(session, tickers, NOW)

    assert (written, skipped) == (2, 1)
