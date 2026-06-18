"""Self-contained tests for activated-products discovery + window logic.

No DB or IBKR connection required — uses fakes. Run with:

    uv run python scripts/test_activated_products.py
"""

from __future__ import annotations

import datetime as dt
import sys

from src.models import (
    PRODUCT_DISCOVERY_ACTIVE,
    PRODUCT_DISCOVERY_NEEDS_DISAMBIGUATION,
    PRODUCT_DISCOVERY_UNKNOWN_SYMBOL,
)
from src.services.contract_sync import (
    _add_months,
    _is_within_window,
    discover_product_metadata,
)


class _FakeContract:
    def __init__(self, con_id: int, exchange: str, multiplier: str = "1000", trading_class: str = "ZB", expiry: str = "20260919"):
        self.conId = con_id
        self.exchange = exchange
        self.multiplier = multiplier
        self.tradingClass = trading_class
        self.lastTradeDateOrContractMonth = expiry


class _FakeDetail:
    def __init__(self, contract: _FakeContract, long_name: str = "US Treasury Bond", valid_exchanges: str = "CBOT,QBALGO", min_tick: float = 0.03125):
        self.contract = contract
        self.longName = long_name
        self.validExchanges = valid_exchanges
        self.minTick = min_tick


class _FakeIB:
    def __init__(self, details, raise_exc: Exception | None = None):
        self._details = details
        self._raise = raise_exc

    def reqContractDetails(self, spec):  # noqa: ARG002
        if self._raise is not None:
            raise self._raise
        return self._details


def test_add_months() -> None:
    assert _add_months(dt.date(2026, 6, 18), 12) == dt.date(2027, 6, 18)
    # Day clamps to end of a shorter month.
    assert _add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    # Year rollover.
    assert _add_months(dt.date(2026, 12, 15), 1) == dt.date(2027, 1, 15)


def test_is_within_window() -> None:
    today = dt.date(2026, 6, 18)
    cutoff = _add_months(today, 12)
    assert _is_within_window("20260720", today, cutoff) is True
    assert _is_within_window("20270901", today, cutoff) is False  # beyond window
    assert _is_within_window("20260101", today, cutoff) is False  # already expired
    assert _is_within_window(None, today, cutoff) is False
    assert _is_within_window("garbage", today, cutoff) is False


def test_discover_single_exchange() -> None:
    ib = _FakeIB([_FakeDetail(_FakeContract(1, "CBOT")), _FakeDetail(_FakeContract(2, "CBOT"))])
    d = discover_product_metadata(ib, "ZB")
    assert d.status == PRODUCT_DISCOVERY_ACTIVE
    assert d.exchange == "CBOT"
    assert d.multiplier == "1000"
    assert d.trading_class == "ZB"
    assert d.long_name == "US Treasury Bond"
    assert d.valid_exchanges == "CBOT,QBALGO"
    assert d.min_tick == 0.03125
    assert len(d.details) == 2


def test_discover_multiple_exchanges() -> None:
    ib = _FakeIB([_FakeDetail(_FakeContract(1, "CBOT")), _FakeDetail(_FakeContract(2, "ECBOT"))])
    d = discover_product_metadata(ib, "ZB")
    assert d.status == PRODUCT_DISCOVERY_NEEDS_DISAMBIGUATION
    assert d.exchange is None
    assert d.exchanges == ["CBOT", "ECBOT"]


def test_discover_zero_results() -> None:
    d = discover_product_metadata(_FakeIB([]), "ZZZ")
    assert d.status == PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
    assert d.exchange is None


def test_discover_request_failure() -> None:
    d = discover_product_metadata(_FakeIB([], raise_exc=RuntimeError("boom")), "ZB")
    assert d.status == PRODUCT_DISCOVERY_UNKNOWN_SYMBOL
    assert d.error is not None and "boom" in d.error


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
