"""Sync combo/spread positions from IBKR TWS into Postgres.

Detects BAG (combo) positions from ib.positions() and stores them
in the combo_positions + combo_position_legs tables.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ib_async import IB
from sqlalchemy import Engine, delete, inspect, select
from sqlalchemy.orm import Session

from src.models import Account, ComboPosition, ComboPositionLeg

logger = logging.getLogger(__name__)


def check_combo_tables_ready(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for required in ("combo_positions", "combo_position_legs", "accounts"):
        if required not in tables:
            raise RuntimeError(f"'{required}' table does not exist. Run: task migrate")


def _get_or_create_account(session: Session, account_string: str) -> int:
    row = session.execute(select(Account).where(Account.account == account_string)).scalar_one_or_none()
    if row is None:
        row = Account(account=account_string)
        session.add(row)
        session.flush()
    return row.id


def _build_combo_key(account_id: int, combo_legs: list) -> str:
    """Deterministic key from account + normalized leg conid:ratio pairs."""
    parts = []
    for leg in sorted(combo_legs, key=lambda l: l.conId):
        parts.append(f"{leg.conId}:{leg.ratio}")
    return f"{account_id}:" + "|".join(parts)


def _contract_to_raw(contract, position_obj) -> dict:
    """Serialize a BAG contract + position into a raw dict for storage."""
    legs_raw = []
    for leg in contract.comboLegs or []:
        legs_raw.append(
            {
                "conId": leg.conId,
                "ratio": leg.ratio,
                "action": leg.action,
                "exchange": leg.exchange,
            }
        )
    return {
        "conId": contract.conId,
        "symbol": contract.symbol,
        "secType": contract.secType,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "localSymbol": contract.localSymbol,
        "tradingClass": contract.tradingClass,
        "comboLegs": legs_raw,
        "position": position_obj.position,
        "avgCost": position_obj.avgCost,
    }


def sync_combo_positions_once(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    connect_timeout_seconds: float = 20.0,
) -> dict:
    """Fetch positions from TWS, extract BAG combos, and upsert into Postgres.

    Returns dict with sync metrics.
    """
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(
                "Timed out connecting to TWS/Gateway while fetching combo positions "
                f"(host={host}, port={port}, client_id={client_id}, timeout={connect_timeout_seconds}s)."
            ) from exc

        positions = ib.positions()
        bag_positions = [p for p in positions if p.contract.secType == "BAG"]

        now = datetime.now(timezone.utc)
        metrics = {"accounts": 0, "combos_upserted": 0, "legs_upserted": 0}

        with Session(engine) as session:
            if not bag_positions:
                logger.info("No BAG (combo) positions found.")
                session.commit()
                return metrics

            # Collect accounts that have BAG positions
            bag_accounts = {p.account for p in bag_positions if p.account}
            account_lookup: dict[str, int] = {}
            for acct_str in bag_accounts:
                account_lookup[acct_str] = _get_or_create_account(session, acct_str)

            metrics["accounts"] = len(bag_accounts)

            # Replace semantics: delete existing combos for these accounts (source=tws),
            # then insert fresh. Cascade deletes legs.
            for account_id in account_lookup.values():
                session.execute(
                    delete(ComboPosition).where(
                        ComboPosition.account_id == account_id,
                        ComboPosition.source == "tws",
                    )
                )

            for pos in bag_positions:
                contract = pos.contract
                combo_legs = contract.comboLegs or []
                if not combo_legs:
                    logger.warning(
                        "BAG position for %s has no comboLegs, skipping (conId=%s)",
                        contract.symbol,
                        contract.conId,
                    )
                    continue

                account_id = account_lookup[pos.account]
                combo_key = _build_combo_key(account_id, combo_legs)
                raw = _contract_to_raw(contract, pos)

                combo_row = ComboPosition(
                    account_id=account_id,
                    source="tws",
                    combo_key=combo_key,
                    name=contract.localSymbol or contract.symbol,
                    description=contract.symbol,
                    position=pos.position,
                    avg_price=pos.avgCost,
                    raw=raw,
                    fetched_at=now,
                )
                session.add(combo_row)
                session.flush()
                metrics["combos_upserted"] += 1

                for leg in combo_legs:
                    leg_row = ComboPositionLeg(
                        combo_position_id=combo_row.id,
                        con_id=leg.conId,
                        ratio=leg.ratio,
                        raw={"conId": leg.conId, "ratio": leg.ratio, "action": leg.action, "exchange": leg.exchange},
                    )
                    session.add(leg_row)
                    metrics["legs_upserted"] += 1

            session.commit()

        logger.info("Combo position sync complete: %s", metrics)
        return metrics
    finally:
        if ib.isConnected():
            ib.disconnect()
