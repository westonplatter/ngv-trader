"""Dump TWS order payloads, anonymized, for the working-orders S0 spike.

Read-only: connects, fetches or listens, and writes JSON. It never places,
modifies, or cancels an order. Every broker identifier is replaced before
anything is written, so the output can become a test fixture.

Usage (run seat, TWS running):
  # Snapshot: the three fetches the order sync uses
  uv run python scripts/dump_open_orders.py --env prod --client-id 0 \
      --out tests/fixtures/tws_orders/snapshot_single_leg.json

  # Listen for push events for 120 s at client 0, bound to new TWS orders
  uv run python scripts/dump_open_orders.py --env prod --client-id 0 \
      --auto-open --listen 120 --out tests/fixtures/tws_orders/events_spread.json

If BROKER_TWS_PORT is an op:// reference, prefix with
`op run --env-file=.env.<env> --`.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from ib_async import IB, Fill, Trade

from src.utils.env_vars import get_int_env

INT32_MAX = 2**31 - 1
SAMPLE_ACCOUNTS = ["U1234567", "U9999999", "U8675309", "U7654321"]


@dataclass
class Anonymizer:
    """Maps real broker identifiers to stable generic ones within one run.

    Zero and empty values pass through unchanged: the spike needs to see
    when TWS reports permId 0 or orderId 0.
    """

    maps: dict[str, dict[Any, Any]] = field(default_factory=dict)
    perm_id_exceeds_int32: bool = False

    def _map(self, kind: str, value: Any, make: Any) -> Any:
        if value in (None, 0, ""):
            return value
        table = self.maps.setdefault(kind, {})
        if value not in table:
            table[value] = make(len(table))
        return table[value]

    def account(self, value: str | None) -> str | None:
        def make(i: int) -> str:
            if i >= len(SAMPLE_ACCOUNTS):
                raise ValueError("more accounts than sample IDs; extend SAMPLE_ACCOUNTS and the data check")
            return SAMPLE_ACCOUNTS[i]

        return self._map("account", value, make)

    def con_id(self, value: int | None) -> int | None:
        return self._map("con_id", value, lambda i: 400000001 + i)

    def perm_id(self, value: int | None) -> int | None:
        if value is not None and value > INT32_MAX:
            self.perm_id_exceeds_int32 = True
        return self._map("perm_id", value, lambda i: 7777777 + i * 1111111)

    def order_id(self, value: int | None) -> int | None:
        return self._map("order_id", value, lambda i: 9000000001 + i)

    def exec_id(self, value: str | None) -> str | None:
        return self._map("exec_id", value, lambda i: f"0000abcd.{12345678 + i}.01.01")

    def label(self, kind: str, value: str | None) -> str | None:
        if value and value.startswith("ngtrader-order-"):
            return value
        return self._map(kind, value, lambda i: f"{kind.upper()}-{i + 1}")


def _num(value: Any) -> float | None:
    # ib_async v3 returns Decimal | None for quantities and prices.
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _contract(contract: Any, anon: Anonymizer) -> dict[str, Any]:
    legs = getattr(contract, "comboLegs", None) or []
    return {
        "secType": contract.secType,
        "conId": anon.con_id(contract.conId),
        "symbol": contract.symbol,
        "localSymbol": contract.localSymbol,
        "exchange": contract.exchange,
        "currency": contract.currency,
        "lastTradeDateOrContractMonth": contract.lastTradeDateOrContractMonth,
        "strike": _num(contract.strike),
        "right": contract.right,
        "multiplier": contract.multiplier,
        "comboLegs": [
            {
                "conId": anon.con_id(leg.conId),
                "ratio": leg.ratio,
                "action": leg.action,
                "exchange": leg.exchange,
                "openClose": leg.openClose,
            }
            for leg in legs
        ],
    }


def _trade(trade: Trade, anon: Anonymizer) -> dict[str, Any]:
    order = trade.order
    status = trade.orderStatus
    return {
        "contract": _contract(trade.contract, anon),
        "order": {
            "action": order.action,
            "totalQuantity": _num(order.totalQuantity),
            "orderType": order.orderType,
            "lmtPrice": _num(order.lmtPrice),
            "auxPrice": _num(order.auxPrice),
            "tif": order.tif,
            "account": anon.account(order.account),
            "permId": anon.perm_id(order.permId),
            "orderId": anon.order_id(order.orderId),
            "clientId": order.clientId,
            "parentId": anon.order_id(order.parentId),
            "ocaGroup": anon.label("oca", order.ocaGroup),
            "orderRef": anon.label("ref", order.orderRef),
            "orderComboLegs": [_num(leg.price) for leg in (order.orderComboLegs or [])],
        },
        "orderStatus": {
            "status": status.status,
            "filled": _num(status.filled),
            "remaining": _num(status.remaining),
            "avgFillPrice": _num(status.avgFillPrice),
            "permId": anon.perm_id(status.permId),
            "clientId": status.clientId,
        },
    }


def _fill(fill: Fill, anon: Anonymizer) -> dict[str, Any]:
    execution = fill.execution
    return {
        "execId": anon.exec_id(execution.execId),
        "permId": anon.perm_id(execution.permId),
        "orderId": anon.order_id(execution.orderId),
        "clientId": execution.clientId,
        "side": execution.side,
        "shares": _num(execution.shares),
        "price": _num(execution.price),
        "conId": anon.con_id(fill.contract.conId),
        "secType": fill.contract.secType,
    }


def snapshot(ib: IB, anon: Anonymizer) -> dict[str, Any]:
    ib.reqOpenOrders()
    ib.waitOnUpdate(timeout=1.0)
    return {
        "openTrades": [_trade(t, anon) for t in ib.openTrades()],
        "reqAllOpenOrders": [_trade(t, anon) for t in ib.reqAllOpenOrders()],
        "reqCompletedOrders": [_trade(t, anon) for t in ib.reqCompletedOrders(apiOnly=False)],
    }


def listen(ib: IB, anon: Anonymizer, seconds: float) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    start = time.monotonic()

    def record(name: str, payload: dict[str, Any]) -> None:
        # Offsets, not wall-clock times, so the fixture carries no trade dates.
        events.append({"t": round(time.monotonic() - start, 3), "event": name, **payload})
        print(f"{events[-1]['t']:>8.3f}s {name}")

    ib.openOrderEvent += lambda trade: record("openOrder", _trade(trade, anon))
    ib.orderStatusEvent += lambda trade: record("orderStatus", _trade(trade, anon))
    ib.execDetailsEvent += lambda trade, fill: record("execDetails", {**_trade(trade, anon), "fill": _fill(fill, anon)})
    print(f"Listening for {seconds:.0f}s. Enter, change, or cancel orders in TWS now.")
    ib.sleep(seconds)
    return events


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump anonymized TWS order payloads (read-only).")
    parser.add_argument("--env", choices=["dev", "prod"], default="dev")
    parser.add_argument("--client-id", type=int, required=True, help="0, or the TWS Master API client ID")
    parser.add_argument("--auto-open", action="store_true", help="call reqAutoOpenOrders(True); client 0 only")
    parser.add_argument("--listen", type=float, default=0, help="seconds to log push events instead of a snapshot")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    env_file = f".env.{args.env}"
    if not os.path.exists(env_file):
        raise SystemExit(f"{env_file} not found")
    load_dotenv(env_file)
    port = get_int_env("BROKER_TWS_PORT", 7497)

    ib = IB()
    ib.connect("127.0.0.1", port, clientId=args.client_id, readonly=True)
    anon = Anonymizer()
    try:
        if args.auto_open:
            ib.reqAutoOpenOrders(True)
        body: dict[str, Any] = {"client_id": args.client_id, "auto_open": args.auto_open}
        if args.listen > 0:
            body["events"] = listen(ib, anon, args.listen)
        else:
            body["snapshot"] = snapshot(ib, anon)
        body["perm_id_exceeds_int32"] = anon.perm_id_exceeds_int32
    finally:
        ib.disconnect()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(body, indent=2) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
