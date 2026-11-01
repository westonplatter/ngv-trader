"""One ingest for settled fills, whatever broker transport they came from.

The FlexQuery and TWS trade syncs used to each carry a copy of the same
pipeline: resolve the parent ``Trade``, upsert the ``TradeExecution`` on its
``ib_exec_id``, backfill the parent's contract fields, enforce canonical
revision flags, and recompute the parent's aggregates. That pipeline lives here
once. A transport only normalizes its rows into :class:`NormalizedFill` and says,
through a :class:`FillSource`, the two things that genuinely differ between
transports: how a parent is matched and whether legs are re-tagged afterwards.

Combos: a multi-leg spread arrives two ways. TWS reports the spread as its own
``BAG`` fill plus one fill per leg (``is_combo_summary`` on the BAG fill);
FlexQuery reports only the legs, sharing a ``brokerageOrderID``
(``combo_key`` on each leg), and the summary row is synthesized here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from functools import reduce
from math import gcd
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import Trade, TradeExecution
from src.services.sync_common import (
    _enforce_canonical_flags,
    _ensure_account,
    _parse_exec_id,
    _recompute_trade_aggregates,
)

logger = logging.getLogger("fill_ingest")

_SIDE_NORMALIZATION = {"BOT": "BUY", "SLD": "SELL"}


def normalize_side(raw_value: str | None) -> str | None:
    """``BUY``/``SELL`` from any broker spelling: ``"BUY (O)"``, ``"BOT"``, ``"SLD"``.

    An unrecognized value is returned upper-cased, with a warning, rather than
    dropped: the fill is still real, its side just needs a look.
    """
    if raw_value is None:
        return None
    base = raw_value.split("(", 1)[0].strip().upper()
    normalized = _SIDE_NORMALIZATION.get(base, base)
    if normalized not in {"BUY", "SELL"}:
        logger.warning("Unrecognized side value: %r", raw_value)
    return normalized


@dataclass(frozen=True)
class FillSource:
    """What differs per transport once fills are normalized."""

    # Value written to the ``data_source`` column of trades and executions.
    name: str
    # Whether the composite parent match (account, order id, symbol, side) also
    # requires the same trade date. TWS order ids are per session and repeat
    # across days, so it must; a FlexQuery ``ibOrderID`` is unique, and the
    # date check only produced duplicate parents at timezone boundaries.
    composite_match_uses_trade_date: bool
    # Whether to re-tag ``standalone`` siblings of a ``combo_summary`` as
    # ``leg`` after the loop. TWS needs it: the BAG fill and its legs can
    # arrive in different batches. FlexQuery legs are tagged on the way in.
    retag_legs_after_ingest: bool


FLEX_SOURCE = FillSource(name="flex", composite_match_uses_trade_date=False, retag_legs_after_ingest=False)
TWS_SOURCE = FillSource(name="tws", composite_match_uses_trade_date=True, retag_legs_after_ingest=True)


@dataclass(frozen=True)
class NormalizedFill:
    """One settled fill in the shape the ingest writes."""

    account_code: str
    ib_exec_id: str
    executed_at: datetime  # tz-aware
    quantity: float
    price: float
    side: str | None
    symbol: str | None
    sec_type: str | None
    con_id: int | None
    exchange: str | None
    currency: str | None
    commission: float | None
    raw: dict[str, Any]
    ib_perm_id: int | None = None
    ib_order_id: int | None = None
    order_ref: str | None = None
    liquidity: str | None = None
    flex_transaction_id: int | None = None
    # Set on every leg of a multi-leg combo the transport does not summarize
    # itself: legs sharing a key share one ``BAG`` parent, and one summary row
    # is synthesized over them after the loop.
    combo_key: str | None = None
    # The spread's underlying symbol, for that parent's ``symbol``.
    combo_underlying: str | None = None
    # True when the transport reports the spread as its own fill (TWS ``BAG``).
    is_combo_summary: bool = False

    @property
    def exec_role(self) -> str:
        if self.is_combo_summary:
            return "combo_summary"
        if self.combo_key is not None:
            return "leg"
        return "standalone"

    @property
    def trade_date(self) -> str:
        return self.executed_at.strftime("%Y-%m-%d")


@dataclass
class IngestResult:
    """What one ingest wrote."""

    upserted: int = 0  # rows written, new or updated
    inserted: int = 0  # of which new
    canonical_changes: int = 0
    combo_summaries: int = 0
    touched_trade_ids: set[int] = field(default_factory=set)

    @property
    def updated(self) -> int:
        return self.upserted - self.inserted


# ---------------------------------------------------------------------------
# Parent resolution
# ---------------------------------------------------------------------------


def _new_trade(fill: NormalizedFill, account_id: int, source: FillSource, now: datetime, **overrides: Any) -> Trade:
    values: dict[str, Any] = dict(
        account_id=account_id,
        ib_perm_id=fill.ib_perm_id,
        order_ref=fill.order_ref,
        ib_order_id=fill.ib_order_id,
        symbol=fill.symbol,
        side=fill.side,
        status="partial",
        data_source=source.name,
        fetched_at=now,
        created_at=now,
        updated_at=now,
    )
    values.update(overrides)
    return Trade(**values)


def resolve_parent_trade(session: Session, fill: NormalizedFill, account_id: int, source: FillSource, now: datetime) -> Trade:
    """Find or create the parent ``Trade`` for a fill, in resolution order:

    1. ``(account_id, ib_perm_id)`` when the perm id is meaningful (TWS only;
       FlexQuery carries none).
    2. ``(account_id, order_ref)`` when the ref is one of ours (``ngtrader-*``).
       Generic tool refs like ``SpreadTrader`` are shared across unrelated
       trades and are never a key.
    3. ``(account_id, ib_order_id, symbol, side)``, plus the trade date when
       the source says so.

    A tier that applies but finds nothing creates the trade; it does not fall
    through to the next tier.
    """
    existing = _match_parent_trade(session, fill, account_id, source)
    if existing is not None:
        return existing
    return _create(session, _new_trade(fill, account_id, source, now))


def _match_parent_trade(session: Session, fill: NormalizedFill, account_id: int, source: FillSource) -> Trade | None:
    if fill.ib_perm_id is not None and fill.ib_perm_id > 0:
        return session.execute(select(Trade).where(Trade.account_id == account_id, Trade.ib_perm_id == fill.ib_perm_id)).scalars().first()

    if fill.order_ref and fill.order_ref.startswith("ngtrader-"):
        return session.execute(select(Trade).where(Trade.account_id == account_id, Trade.order_ref == fill.order_ref)).scalars().first()

    candidates = (
        session.execute(
            select(Trade)
            .where(
                Trade.account_id == account_id,
                Trade.ib_order_id == fill.ib_order_id,
                Trade.symbol == fill.symbol,
                Trade.side == fill.side,
            )
            .order_by(Trade.id.asc())
        )
        .scalars()
        .all()
    )
    for candidate in candidates:
        if not source.composite_match_uses_trade_date:
            return candidate
        if candidate.first_executed_at is not None and candidate.first_executed_at.strftime("%Y-%m-%d") == fill.trade_date:
            return candidate
    return None


def _resolve_combo_parent(
    session: Session,
    fill: NormalizedFill,
    account_id: int,
    source: FillSource,
    now: datetime,
    cache: dict[str, Trade],
) -> Trade:
    """The one ``BAG`` parent every leg of a synthesized combo shares.

    Re-attaches to the parent a prior run created, found through the summary
    row that carries the combo key in its raw payload; otherwise creates it.
    """
    key = fill.combo_key
    assert key is not None  # noqa: S101 — caller checks
    cached = cache.get(key)
    if cached is not None:
        return cached
    # ``raw`` is JSON (not JSONB), so use json_extract_path_text.
    existing_summary = (
        session.execute(
            select(TradeExecution)
            .where(
                TradeExecution.account_id == account_id,
                TradeExecution.exec_role == "combo_summary",
                func.json_extract_path_text(TradeExecution.raw, "brokerage_order_id") == key,
            )
            .limit(1)
        )
        .scalars()
        .first()
    )
    trade = session.get(Trade, existing_summary.trade_id) if existing_summary is not None else None
    if trade is None:
        trade = _create(
            session,
            _new_trade(fill, account_id, source, now, ib_perm_id=None, ib_order_id=None, symbol=fill.combo_underlying, sec_type="BAG", side=None),
        )
    cache[key] = trade
    return trade


def _create(session: Session, trade: Trade) -> Trade:
    session.add(trade)
    session.flush()
    return trade


def _backfill_contract_fields(trade: Trade, fill: NormalizedFill) -> None:
    if trade.symbol is None and fill.symbol:
        trade.symbol = fill.symbol
    if trade.sec_type is None and fill.sec_type:
        trade.sec_type = fill.sec_type
    if trade.exchange is None and fill.exchange:
        trade.exchange = fill.exchange
    if trade.currency is None and fill.currency:
        trade.currency = fill.currency


# ---------------------------------------------------------------------------
# Writing executions
# ---------------------------------------------------------------------------


def _upsert_execution(session: Session, *, account_id: int, trade_id: int, fill: NormalizedFill, source: FillSource, now: datetime) -> tuple[str, bool]:
    """Insert-or-update the execution on ``ib_exec_id``.

    Returns ``(exec_id_base, inserted)``. ``xmax = 0`` on the returned row is
    how Postgres says the row was inserted rather than updated.
    """
    exec_id_base, exec_revision = _parse_exec_id(fill.ib_exec_id)
    stmt = (
        insert(TradeExecution)
        .values(
            trade_id=trade_id,
            account_id=account_id,
            ib_exec_id=fill.ib_exec_id,
            exec_id_base=exec_id_base,
            exec_revision=exec_revision,
            ib_perm_id=fill.ib_perm_id,
            ib_order_id=fill.ib_order_id,
            order_ref=fill.order_ref,
            sec_type=fill.sec_type,
            con_id=fill.con_id,
            exec_role=fill.exec_role,
            executed_at=fill.executed_at,
            quantity=fill.quantity,
            price=fill.price,
            side=fill.side,
            exchange=fill.exchange,
            currency=fill.currency,
            liquidity=fill.liquidity,
            commission=fill.commission,
            is_canonical=True,  # corrected by _enforce_canonical_flags below
            data_source=source.name,
            flex_transaction_id=fill.flex_transaction_id,
            raw=fill.raw,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["ib_exec_id"],
            set_={
                "trade_id": trade_id,
                "quantity": fill.quantity,
                "price": fill.price,
                "commission": fill.commission,
                "sec_type": fill.sec_type,
                "con_id": fill.con_id,
                "exec_role": fill.exec_role,
                "data_source": source.name,
                "flex_transaction_id": fill.flex_transaction_id,
                "raw": fill.raw,
                "fetched_at": now,
                "updated_at": now,
            },
        )
        .returning(literal_column("(xmax = 0)"))
    )
    inserted = bool(session.execute(stmt).scalar())
    return exec_id_base, inserted


def _synthesize_combo_summary(  # noqa: C901, PLR0912, PLR0915 — one linear derivation
    session: Session,
    *,
    parent: Trade,
    combo_key: str,
    legs: list[NormalizedFill],
    source: FillSource,
    now: datetime,
) -> tuple[str, bool] | None:
    """Upsert the ``combo_summary`` row for legs the transport did not summarize.

    Quantity is the gcd of the legs' sizes, price the net cash per unit, side
    the sign of that cash. Keyed on the leg numbering's reserved ``01`` slot
    when every leg shares a prefix, else on the combo key, so it is idempotent.
    Returns ``(exec_id_base, inserted)``, or ``None`` when there is nothing to
    summarize.
    """
    if len(legs) < 2:
        return None

    quantities = [leg.quantity for leg in legs]
    signed_cash = sum(leg.quantity * leg.price for leg in legs)
    commissions = [leg.commission for leg in legs if leg.commission is not None]
    earliest = min(leg.executed_at for leg in legs)
    leg_exec_ids = [leg.ib_exec_id for leg in legs if leg.ib_exec_id]
    order_refs = [leg.order_ref or "" for leg in legs]
    currencies = {leg.currency for leg in legs if leg.currency}
    exchanges = {leg.exchange for leg in legs if leg.exchange}

    # gcd over absolute integer quantities; falls back to 1 if any non-integer
    abs_int_qtys: list[int] = []
    for q in quantities:
        a = abs(q)
        if a == 0:
            continue
        if float(int(a)) == a:
            abs_int_qtys.append(int(a))
        else:
            abs_int_qtys = []
            break
    combo_qty = reduce(gcd, abs_int_qtys) if abs_int_qtys else 1
    if combo_qty <= 0:
        combo_qty = 1

    combo_price = signed_cash / combo_qty if combo_qty else 0.0
    combo_side = "BUY" if signed_cash > 0 else "SELL"
    combo_commission = sum(commissions) if commissions else None
    combo_order_ref = order_refs[0] if order_refs and all(order_refs) and len(set(order_refs)) == 1 else None

    # IBKR formats ibExecID as `<acct-prefix>.<order-prefix>.<leg>.<revision>`
    # and reserves leg "01" for the BAG slot (legs are .02, .03, ...).
    combo_exec_id: str | None = None
    prefixes = {".".join(parts[:2]) for ex_id in leg_exec_ids for parts in [ex_id.split(".")] if len(parts) >= 4}
    if len(prefixes) == 1:
        combo_exec_id = f"{next(iter(prefixes))}.01.01"
    if combo_exec_id is None:
        combo_exec_id = f"{combo_key}.combo"
    combo_exec_id_base, _ = _parse_exec_id(combo_exec_id)

    one_exchange = next(iter(exchanges)) if len(exchanges) == 1 else None
    one_currency = next(iter(currencies)) if len(currencies) == 1 else None
    raw = {
        "synthetic": True,
        "brokerage_order_id": combo_key,
        "leg_ib_exec_ids": leg_exec_ids,
        "leg_count": len(legs),
        "signed_net_cash": signed_cash,
        "leg_quantities": quantities,
        # TWS-shaped contract so the display layer renders the BAG row like a
        # TWS combo (e.g. "AAPL Combo").
        "contract": {
            "conId": None,
            "symbol": parent.symbol,
            "secType": "BAG",
            "exchange": one_exchange,
            "currency": one_currency,
            "localSymbol": None,
            "lastTradeDateOrContractMonth": None,
            "strike": None,
            "right": None,
            "tradingClass": None,
            "multiplier": None,
        },
    }

    stmt = (
        insert(TradeExecution)
        .values(
            trade_id=parent.id,
            account_id=parent.account_id,
            ib_exec_id=combo_exec_id,
            exec_id_base=combo_exec_id_base,
            exec_revision=1,
            ib_perm_id=None,
            ib_order_id=None,
            order_ref=combo_order_ref,
            sec_type="BAG",
            con_id=None,
            exec_role="combo_summary",
            executed_at=earliest,
            quantity=float(combo_qty),
            price=combo_price,
            side=combo_side,
            exchange=one_exchange,
            currency=one_currency,
            liquidity=None,
            commission=combo_commission,
            is_canonical=True,
            data_source=source.name,
            flex_transaction_id=None,
            raw=raw,
            fetched_at=now,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=["ib_exec_id"],
            set_={
                "trade_id": parent.id,
                "quantity": float(combo_qty),
                "price": combo_price,
                "side": combo_side,
                "commission": combo_commission,
                "exec_role": "combo_summary",
                "sec_type": "BAG",
                "executed_at": earliest,
                "order_ref": combo_order_ref,
                "raw": raw,
                "fetched_at": now,
                "updated_at": now,
            },
        )
        .returning(literal_column("(xmax = 0)"))
    )
    inserted = bool(session.execute(stmt).scalar())
    return combo_exec_id_base, inserted


def _retag_combo_legs(session: Session, trade_ids: set[int]) -> None:
    """Where a trade holds a ``combo_summary``, its ``standalone`` fills are legs.

    Also marks the parent ``BAG``. Needed when the summary fill and its legs
    arrive in different batches, so the legs could not be tagged on the way in.
    """
    for trade_id in trade_ids:
        trade_execs = session.execute(select(TradeExecution).where(TradeExecution.trade_id == trade_id)).scalars().all()
        if not any(ex.exec_role == "combo_summary" for ex in trade_execs):
            continue
        parent_trade = session.get(Trade, trade_id)
        if parent_trade and parent_trade.sec_type != "BAG":
            parent_trade.sec_type = "BAG"
        for ex in trade_execs:
            if ex.exec_role == "standalone":
                ex.exec_role = "leg"
        session.flush()


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


@dataclass
class _IngestRun:
    """Per-call state: the caches and the bookkeeping the final passes need."""

    session: Session
    source: FillSource
    now: datetime
    result: IngestResult = field(default_factory=IngestResult)
    accounts: dict[str, int] = field(default_factory=dict)
    combo_parents: dict[str, Trade] = field(default_factory=dict)
    legs_by_combo: dict[str, list[NormalizedFill]] = field(default_factory=dict)
    affected_bases: list[tuple[int, str]] = field(default_factory=list)

    def account_id(self, account_code: str) -> int:
        account_id = self.accounts.get(account_code)
        if account_id is None:
            account_id = self.accounts[account_code] = _ensure_account(self.session, account_code).id
        return account_id

    def record(self, trade_id: int, account_id: int, exec_id_base: str, inserted: bool) -> None:
        self.result.upserted += 1
        self.result.inserted += int(inserted)
        self.affected_bases.append((account_id, exec_id_base))
        self.result.touched_trade_ids.add(trade_id)

    def write_fill(self, fill: NormalizedFill) -> None:
        account_id = self.account_id(fill.account_code)
        if fill.combo_key is not None:
            trade = _resolve_combo_parent(self.session, fill, account_id, self.source, self.now, self.combo_parents)
            self.legs_by_combo.setdefault(fill.combo_key, []).append(fill)
        else:
            trade = resolve_parent_trade(self.session, fill, account_id, self.source, self.now)
            _backfill_contract_fields(trade, fill)
        exec_id_base, inserted = _upsert_execution(self.session, account_id=account_id, trade_id=trade.id, fill=fill, source=self.source, now=self.now)
        self.record(trade.id, account_id, exec_id_base, inserted)

    def write_combo_summaries(self) -> None:
        for combo_key, legs in self.legs_by_combo.items():
            parent = self.combo_parents[combo_key]
            summary = _synthesize_combo_summary(self.session, parent=parent, combo_key=combo_key, legs=legs, source=self.source, now=self.now)
            if summary is None:
                continue
            exec_id_base, inserted = summary
            self.result.combo_summaries += 1
            self.record(parent.id, parent.account_id, exec_id_base, inserted)

    def finish(self, skip_aggregate_recompute: bool) -> IngestResult:
        for account_id, exec_id_base in self.affected_bases:
            self.result.canonical_changes += _enforce_canonical_flags(self.session, account_id, exec_id_base)
        if self.source.retag_legs_after_ingest:
            _retag_combo_legs(self.session, self.result.touched_trade_ids)
        if not skip_aggregate_recompute:
            for trade_id in self.result.touched_trade_ids:
                _recompute_trade_aggregates(self.session, trade_id, self.now)
        return self.result


def ingest_fills(
    session: Session,
    fills: list[NormalizedFill],
    *,
    source: FillSource,
    now: datetime,
    skip_aggregate_recompute: bool = False,
) -> IngestResult:
    """Write normalized fills: parents, executions, combo summaries, canonical
    flags, and parent aggregates. The caller owns the session and commits.

    ``skip_aggregate_recompute`` defers the per-trade aggregate pass; a backfill
    that ingests many windows runs it once at the end over
    ``touched_trade_ids`` instead of after every chunk.
    """
    run = _IngestRun(session=session, source=source, now=now)
    for fill in fills:
        run.write_fill(fill)
    run.write_combo_summaries()
    return run.finish(skip_aggregate_recompute)
