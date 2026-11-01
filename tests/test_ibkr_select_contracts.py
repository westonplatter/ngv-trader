"""IB-side contract selection: the template and its per-sec_type selectors.

No DB or IBKR connection. A duck-typed `_FakeIB` stands in for `IB` and records the
specs it was asked about, so these tests pin both what each selector sends to the
broker and how it picks from the answer (STK, FUT, OPT, FOP, and the "no contracts"
errors). Ids are anonymized placeholders from the allowed list.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from ib_async import IB, Contract

from src.services.ibkr_select_contracts import (
    ContractSelectionRequest,
    ContractSelectorFactory,
    FutureContractSelector,
    FutureOptionContractSelector,
    IndexContractSelector,
    OptionContractSelector,
    OptionLikeSelector,
    StockContractSelector,
    select_contract_for_watchlist,
)

_UNDERLYING_CONID = 400000008
_QUALIFIED_CONID = 400000009


class _FakeIB:
    """Answers the handful of IB calls the selectors make."""

    def __init__(
        self,
        contracts: list[Contract] | None = None,
        chains: list[Any] | None = None,
        qualified: list[Contract] | None = None,
    ) -> None:
        self._contracts = contracts or []
        self._chains = chains or []
        self._qualified = qualified
        self.detail_specs: list[Contract] = []
        self.qualify_calls: list[tuple[Contract, ...]] = []
        self.chain_requests: list[dict[str, Any]] = []

    def reqContractDetails(self, spec: Contract) -> list[SimpleNamespace]:  # noqa: N802
        self.detail_specs.append(spec)
        return [SimpleNamespace(contract=contract) for contract in self._contracts]

    def qualifyContracts(self, *specs: Contract) -> list[Contract]:  # noqa: N802
        self.qualify_calls.append(specs)
        if self._qualified is not None:
            return self._qualified
        for spec in specs:
            spec.conId = _UNDERLYING_CONID if spec.secType == "IND" else _QUALIFIED_CONID
        return list(specs)

    def reqSecDefOptParams(self, **kwargs: Any) -> list[Any]:  # noqa: N802
        self.chain_requests.append(kwargs)
        return self._chains


def _ib(fake: _FakeIB) -> IB:
    return cast("IB", fake)


def _contract(
    con_id: int,
    sec_type: str,
    expiry: str = "",
    *,
    strike: float = 0.0,
    right: str = "",
    primary_exchange: str = "",
    exchange: str = "TESTX",
) -> Contract:
    return Contract(
        conId=con_id,
        symbol="TST",
        secType=sec_type,
        lastTradeDateOrContractMonth=expiry,
        strike=strike,
        right=right,
        primaryExchange=primary_exchange,
        exchange=exchange,
    )


def _request(sec_type: str, **overrides: Any) -> ContractSelectionRequest:
    fields: dict[str, Any] = {"symbol": "TST", "sec_type": sec_type, "exchange": "TESTX"}
    fields.update(overrides)
    return ContractSelectionRequest(**fields)


# --- STK / IND -------------------------------------------------------------------


def test_stk_picks_lowest_primary_exchange_then_con_id() -> None:
    fake = _FakeIB(
        [
            _contract(400000003, "STK", primary_exchange="NYSE"),
            _contract(400000002, "STK", primary_exchange="ARCA"),
            _contract(400000001, "STK", primary_exchange="ARCA"),
        ]
    )
    contract, count = ContractSelectorFactory.create("stk").select(_ib(fake), _request("STK"))
    assert (contract.conId, count) == (400000001, 3)
    spec = fake.detail_specs[0]
    assert (spec.symbol, spec.secType, spec.exchange, spec.currency) == ("TST", "STK", "TESTX", "USD")


def test_ind_picks_lowest_exchange_then_con_id() -> None:
    fake = _FakeIB([_contract(400000002, "IND", exchange="B"), _contract(400000001, "IND", exchange="A")])
    contract, count = IndexContractSelector().select(_ib(fake), _request("IND"))
    assert (contract.conId, count) == (400000001, 2)
    assert fake.detail_specs[0].secType == "IND"


# --- FUT -------------------------------------------------------------------------


def test_fut_filters_by_month_and_sorts_by_expiry() -> None:
    fake = _FakeIB(
        [
            _contract(400000003, "FUT", "20270319"),
            _contract(400000002, "FUT", "20261218"),
            _contract(400000001, "FUT", "20261120"),
        ]
    )
    request = _request("FUT", contract_month="2026-12")
    contract, count = FutureContractSelector().select(_ib(fake), request)
    assert (contract.conId, count) == (400000002, 1)
    # The dash is stripped before the month goes to the broker.
    assert fake.detail_specs[0].lastTradeDateOrContractMonth == "202612"


def test_fut_without_month_returns_nearest_expiry() -> None:
    fake = _FakeIB([_contract(400000002, "FUT", "20270319"), _contract(400000001, "FUT", "20261218")])
    contract, count = FutureContractSelector().select(_ib(fake), _request("FUT"))
    assert (contract.conId, count) == (400000001, 2)
    assert fake.detail_specs[0].lastTradeDateOrContractMonth == ""


def test_fut_full_date_matches_exact_expiry() -> None:
    fake = _FakeIB([_contract(400000002, "FUT", "20261218"), _contract(400000001, "FUT", "20261120")])
    contract, count = FutureContractSelector().select(_ib(fake), _request("FUT", contract_month="20261218"))
    assert (contract.conId, count) == (400000002, 1)


# --- OPT -------------------------------------------------------------------------


def _opt_chain_contracts() -> list[Contract]:
    return [
        _contract(400000001, "OPT", "20261218", strike=100.0, right="C"),
        _contract(400000002, "OPT", "20261218", strike=100.0, right="P"),
        _contract(400000003, "OPT", "20261218", strike=105.0, right="C"),
        _contract(400000004, "OPT", "20270115", strike=100.0, right="C"),
    ]


def test_opt_selects_single_match_and_builds_full_spec() -> None:
    fake = _FakeIB(_opt_chain_contracts())
    request = _request("OPT", contract_month="2026-12", strike=105.0, right="call")
    contract, count = OptionContractSelector().select(_ib(fake), request)
    assert (contract.conId, count) == (400000003, 1)
    spec = fake.detail_specs[0]
    assert (spec.secType, spec.lastTradeDateOrContractMonth, spec.strike, spec.right) == ("OPT", "202612", 105.0, "C")


def test_opt_ambiguous_match_raises_with_candidates() -> None:
    fake = _FakeIB(_opt_chain_contracts())
    with pytest.raises(RuntimeError, match=r"Ambiguous option selection for .* Found 2 matches"):
        OptionContractSelector().select(_ib(fake), _request("OPT", contract_month="2026-12", strike=100.0))


def test_opt_rejects_unknown_right_before_any_broker_call() -> None:
    fake = _FakeIB(_opt_chain_contracts())
    with pytest.raises(ValueError, match="right must be one of"):
        OptionContractSelector().select(_ib(fake), _request("OPT", right="straddle"))
    assert fake.detail_specs == []


# --- FOP -------------------------------------------------------------------------


def _chain(
    trading_class: str = "TC",
    multiplier: str = "50",
    expirations: tuple[str, ...] = ("20261218",),
    strikes: tuple[float, ...] = (100.0, 105.0),
    exchange: str = "TESTX",
) -> SimpleNamespace:
    return SimpleNamespace(
        exchange=exchange,
        tradingClass=trading_class,
        multiplier=multiplier,
        expirations=set(expirations),
        strikes=set(strikes),
    )


def test_fop_build_spec_is_the_plain_option_spec() -> None:
    request = _request("FOP", contract_month="2026-12", strike=100.0, right="PUT")
    spec = FutureOptionContractSelector().build_spec(request)
    assert (spec.symbol, spec.secType, spec.exchange, spec.currency) == ("TST", "FOP", "TESTX", "USD")
    assert (spec.lastTradeDateOrContractMonth, spec.strike, spec.right) == ("202612", 100.0, "P")
    assert spec.tradingClass == ""


def test_fop_select_qualifies_spec_with_chain_trading_class_and_multiplier() -> None:
    fake = _FakeIB(chains=[_chain()])
    request = _request("FOP", contract_month="202612", strike=105.0, right="C")
    contract, count = ContractSelectorFactory.create("FOP").select(_ib(fake), request)
    assert (contract.conId, count) == (_QUALIFIED_CONID, 1)
    assert (contract.tradingClass, contract.multiplier) == ("TC", "50")
    assert (contract.secType, contract.strike, contract.right) == ("FOP", 105.0, "C")
    # The underlying is qualified first, then the chain is requested for it.
    index = fake.qualify_calls[0][0]
    assert (index.secType, index.symbol, index.exchange) == ("IND", "TST", "TESTX")
    assert fake.chain_requests == [
        {
            "underlyingSymbol": "TST",
            "futFopExchange": "TESTX",
            "underlyingSecType": "IND",
            "underlyingConId": _UNDERLYING_CONID,
        }
    ]
    # FOP resolves by qualifying, not by reqContractDetails.
    assert fake.detail_specs == []


def test_fop_prefers_standard_chain_with_most_strikes_over_weeklies() -> None:
    chains = [
        _chain(trading_class="WL1", multiplier="25", strikes=(100.0, 105.0, 110.0)),
        _chain(trading_class="TC", multiplier="50", strikes=(100.0, 105.0)),
    ]
    contract, _ = FutureOptionContractSelector().select(_ib(_FakeIB(chains=chains)), _request("FOP", contract_month="202612"))
    assert (contract.tradingClass, contract.multiplier) == ("TC", "50")


def test_fop_without_chain_metadata_raises() -> None:
    with pytest.raises(RuntimeError, match="No FOP option chain metadata found"):
        FutureOptionContractSelector().select(_ib(_FakeIB(chains=[])), _request("FOP"))


def test_fop_unknown_month_and_strike_raise_chain_errors() -> None:
    fake = _FakeIB(chains=[_chain()])
    with pytest.raises(RuntimeError, match=r"No FOP expirations matching month=202701"):
        FutureOptionContractSelector().select(_ib(fake), _request("FOP", contract_month="202701"))
    with pytest.raises(RuntimeError, match=r"No FOP strike=999.0 .* Available strikes: 100.0, 105.0"):
        FutureOptionContractSelector().select(_ib(fake), _request("FOP", strike=999.0))


def test_fop_unqualifiable_spec_raises() -> None:
    fake = _FakeIB(chains=[_chain()], qualified=[])
    with pytest.raises(RuntimeError, match="Expected exactly one qualified contract"):
        FutureOptionContractSelector().select(_ib(fake), _request("FOP", contract_month="202612"))


# --- no contracts ----------------------------------------------------------------


@pytest.mark.parametrize("sec_type", ["STK", "IND", "FUT", "OPT"])
def test_no_contracts_raises_with_lookup_context(sec_type: str) -> None:
    selector = ContractSelectorFactory.create(sec_type)
    with pytest.raises(RuntimeError, match=rf"No contracts found for TST {sec_type} on TESTX"):
        selector.select(_ib(_FakeIB([])), _request(sec_type))


def test_filtered_out_contracts_raise_no_contracts() -> None:
    fake = _FakeIB([_contract(400000001, "FUT", "20261218")])
    with pytest.raises(RuntimeError, match=r"No contracts found for TST FUT on TESTX month=202701"):
        FutureContractSelector().select(_ib(fake), _request("FUT", contract_month="202701"))


def test_contracts_without_con_id_are_ignored() -> None:
    fake = _FakeIB([_contract(0, "STK"), _contract(400000001, "STK"), _contract(400000001, "STK")])
    contract, count = StockContractSelector().select(_ib(fake), _request("STK"))
    assert (contract.conId, count) == (400000001, 1)


# --- factory and entry point -------------------------------------------------------


@pytest.mark.parametrize(
    ("sec_type", "expected"),
    [
        ("stk", StockContractSelector),
        ("IND", IndexContractSelector),
        ("fut", FutureContractSelector),
        ("OPT", OptionContractSelector),
        ("fop", FutureOptionContractSelector),
    ],
)
def test_factory_creates_selector_for_sec_type(sec_type: str, expected: type) -> None:
    assert type(ContractSelectorFactory.create(sec_type)) is expected


def test_factory_rejects_unsupported_sec_type() -> None:
    with pytest.raises(ValueError, match="Unsupported sec_type 'BOND'"):
        ContractSelectorFactory.create("BOND")


def test_option_selectors_share_hooks_from_option_like_selector() -> None:
    hooks = ("filter_matches", "sort_matches", "validate_matches")
    for selector in (OptionContractSelector, FutureOptionContractSelector):
        assert issubclass(selector, OptionLikeSelector)
        for hook in hooks:
            assert hook not in vars(selector)
    assert OptionContractSelector.sec_type == "OPT"
    assert FutureOptionContractSelector.sec_type == "FOP"


def test_select_contract_for_watchlist_normalizes_request() -> None:
    fake = _FakeIB([_contract(400000001, "FUT", "20261218")])
    contract, count = select_contract_for_watchlist(_ib(fake), "TST", "fut", "TESTX", contract_month="2026-12")
    assert (contract.conId, count) == (400000001, 1)
    assert fake.detail_specs[0].lastTradeDateOrContractMonth == "202612"


def test_select_contract_for_watchlist_keeps_full_date_month() -> None:
    fake = _FakeIB([_contract(400000001, "FUT", "20261218")])
    select_contract_for_watchlist(_ib(fake), "TST", "FUT", "TESTX", contract_month="2026-12-18")
    assert fake.detail_specs[0].lastTradeDateOrContractMonth == "20261218"
