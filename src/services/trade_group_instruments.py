"""Instruments a trade group touched, and the pattern filter over them.

A trade group has no instrument column: it links to executions, and an execution
carries ``con_id`` but no symbol. The instrument is the **underlying root**
(``CL``), resolved from two sources in priority order:

1. ``contracts.symbol`` — the security master. Authoritative and indexed, but
   incomplete: many traded option ``con_id``s never get a contracts row (see the
   ``v_execution_facts`` migration note).
2. ``trade_executions.raw -> 'contract' ->> 'symbol'`` — synthesized by the
   FlexQuery sync from ``underlyingSymbol``. This is the *underlying* root, not
   the OCC/local symbol, which the sync writes to ``contract.localSymbol``.

Filtering runs in SQL (Postgres ``~*``, a case-insensitive POSIX regex) inside a
correlated ``EXISTS`` rather than in Python over a fetched page, so an
instrument filter selects across the whole set *before* any row limit applies.
Matching is unanchored, so ``CL.*`` and ``CL`` both find a CL group and the
caller can anchor explicitly with ``^CL$``.
"""

from __future__ import annotations

import re

from sqlalchemy import func, literal, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from src.models import ContractRef, TradeExecution, TradeGroup, TradeGroupExecution


class InstrumentPatternError(ValueError):
    """The instrument pattern is not a usable regex — surfaces as a 400."""


def validate_instrument_pattern(pattern: str) -> str:
    """Return ``pattern`` if it compiles, else raise :class:`InstrumentPatternError`.

    Compiling in Python first is what keeps a malformed pattern from reaching
    Postgres, where it would surface as a 500 with a raw driver error string.
    Python's ``re`` and Postgres' POSIX regex are not identical dialects, but
    they agree on the malformed cases an operator actually types (``CL[``).
    """
    if pattern is None or not pattern.strip():
        raise InstrumentPatternError("Instrument pattern must not be blank.")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise InstrumentPatternError(f"Invalid instrument pattern {pattern!r}: {exc}") from exc
    return pattern


def _instrument_expr() -> ColumnElement[str]:
    """``COALESCE(contracts.symbol, raw->'contract'->>'symbol')`` — the underlying root."""
    return func.coalesce(ContractRef.symbol, TradeExecution.raw["contract"]["symbol"].as_string())


def _group_executions_join(stmt):
    """Attach the group → execution → contract join every query here shares."""
    return (
        stmt.select_from(TradeGroupExecution)
        .join(TradeExecution, TradeExecution.id == TradeGroupExecution.trade_execution_id)
        .outerjoin(ContractRef, ContractRef.con_id == TradeExecution.con_id)
    )


def trade_group_instruments(
    session: Session,
    group_ids: list[int],
    account_id: int | None = None,
) -> dict[int, list[str]]:
    """``{group_id: sorted distinct instruments}`` for every requested group.

    One query regardless of ``len(group_ids)``. Groups with no executions (or
    with executions whose symbol resolves to nothing) get an empty list rather
    than a missing key, so callers never have to null-guard.

    ``account_id`` narrows to that account's fills, so an account-filtered row
    lists the instruments it actually holds *there* rather than book-wide.
    """
    result: dict[int, list[str]] = {group_id: [] for group_id in group_ids}
    if not group_ids:
        return result

    instrument = _instrument_expr()
    stmt = _group_executions_join(select(TradeGroupExecution.trade_group_id, instrument.label("instrument"))).where(
        TradeGroupExecution.trade_group_id.in_(group_ids),
        instrument.is_not(None),
    )
    if account_id is not None:
        stmt = stmt.where(TradeExecution.account_id == account_id)
    for group_id, symbol in session.execute(stmt.distinct()).all():
        result[group_id].append(symbol)
    for symbols in result.values():
        symbols.sort()
    return result


def instrument_filter_condition(pattern: str) -> ColumnElement[bool]:
    """A ``TradeGroup``-correlated condition: instrument matches, or the name does.

    The name fallback catches a group whose fills predate its contract records —
    or that has no fills yet at all, which is every group on the day it is
    opened.
    """
    validate_instrument_pattern(pattern)
    instrument_matches = (
        _group_executions_join(select(literal(1)))
        .where(
            TradeGroupExecution.trade_group_id == TradeGroup.id,
            _instrument_expr().op("~*")(pattern),
        )
        .correlate(TradeGroup)
        .exists()
    )
    return or_(instrument_matches, TradeGroup.name.op("~*")(pattern))
