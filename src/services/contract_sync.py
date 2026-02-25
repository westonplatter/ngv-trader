"""Sync contract details from IBKR into the contracts table."""

from __future__ import annotations

from datetime import datetime, timezone

from ib_async import IB, Contract
from sqlalchemy import Engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from src.models import ContractRef
from src.services.cl_contracts import (
    format_contract_month_from_expiry,
    infer_contract_month_from_local_symbol,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def sync_contracts(
    engine: Engine,
    host: str,
    port: int,
    client_id: int,
    specs: list[Contract],
    connect_timeout_seconds: float = 20.0,
) -> dict:
    """Fetch contract details from IB for each spec and upsert into the contracts table.

    Returns a summary dict with counts.
    """
    ib = IB()
    try:
        try:
            ib.connect(host, port, clientId=client_id, timeout=connect_timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(f"Timed out connecting to TWS/Gateway for contract sync " f"(host={host}, port={port}, client_id={client_id}).") from exc

        all_con_ids: set[int] = set()
        synced_count = 0
        now = _now_utc()

        for spec in specs:
            contract_details = ib.reqContractDetails(spec)
            if not contract_details:
                continue

            spec_con_ids: set[int] = set()

            with Session(engine) as session:
                for detail in contract_details:
                    contract = detail.contract
                    if contract is None or contract.conId is None or contract.conId == 0:
                        continue

                    raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
                    contract_month = infer_contract_month_from_local_symbol(
                        local_symbol=contract.localSymbol or None,
                        contract_expiry=raw_expiry,
                        sec_type=contract.secType or spec.secType or "FUT",
                    ) or format_contract_month_from_expiry(raw_expiry)

                    values = {
                        "con_id": contract.conId,
                        "symbol": contract.symbol or spec.symbol or "UNKNOWN",
                        "sec_type": contract.secType or spec.secType or "FUT",
                        "exchange": contract.exchange or spec.exchange or "SMART",
                        "currency": contract.currency or spec.currency or "USD",
                        "local_symbol": contract.localSymbol or None,
                        "trading_class": contract.tradingClass or None,
                        "contract_month": contract_month,
                        "contract_expiry": raw_expiry,
                        "multiplier": contract.multiplier or None,
                        "strike": (contract.strike if contract.strike and contract.strike != 0.0 else None),
                        "right": (contract.right if contract.right and contract.right != "?" else None),
                        "primary_exchange": contract.primaryExchange or None,
                        "is_active": True,
                        "fetched_at": now,
                        "updated_at": now,
                    }

                    stmt = (
                        insert(ContractRef)
                        .values(**values, created_at=now)
                        .on_conflict_do_update(
                            index_elements=["con_id"],
                            set_={k: v for k, v in values.items() if k != "con_id"},
                        )
                    )
                    session.execute(stmt)
                    spec_con_ids.add(contract.conId)
                    synced_count += 1

                # Mark contracts for this spec that were NOT returned as inactive
                if spec_con_ids:
                    from sqlalchemy import update

                    session.execute(
                        update(ContractRef)
                        .where(
                            ContractRef.symbol == (spec.symbol or "UNKNOWN"),
                            ContractRef.sec_type == (spec.secType or "FUT"),
                            ContractRef.is_active.is_(True),
                            ContractRef.con_id.not_in(spec_con_ids),
                        )
                        .values(is_active=False, updated_at=now)
                    )

                session.commit()

            all_con_ids.update(spec_con_ids)

        return {
            "synced_count": synced_count,
            "unique_con_ids": len(all_con_ids),
            "specs_count": len(specs),
        }
    finally:
        if ib.isConnected():
            ib.disconnect()
