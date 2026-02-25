"""Factory-method contract selection for IBKR instruments."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from ib_async import IB, Contract, Index

from src.services.cl_contracts import (
    format_contract_month_from_expiry,
    normalize_contract_month_input,
    parse_contract_expiry,
)


@dataclass(frozen=True)
class ContractSelectionRequest:
    symbol: str
    sec_type: str
    exchange: str
    contract_month: str | None = None
    strike: float | None = None
    right: str | None = None
    currency: str = "USD"


def _normalize_contract_month(contract_month: str | None) -> str | None:
    raw = (contract_month or "").strip()
    if not raw:
        return None
    return raw.replace("-", "")


def _normalize_right(right: str | None) -> str | None:
    value = (right or "").strip().upper()
    if not value:
        return None
    if value in {"C", "CALL"}:
        return "C"
    if value in {"P", "PUT"}:
        return "P"
    raise ValueError("right must be one of C/CALL or P/PUT.")


def _contract_month_matches(contract: Contract, contract_month: str | None) -> bool:
    if contract_month is None:
        return True
    raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or None
    contract_month_value = format_contract_month_from_expiry(raw_expiry)
    return contract_month_value == contract_month


def _option_right_matches(contract: Contract, right: str | None) -> bool:
    if right is None:
        return True
    contract_right = (contract.right or "").strip().upper()
    return contract_right == right


def _strike_matches(contract: Contract, strike: float | None) -> bool:
    if strike is None:
        return True
    contract_strike = contract.strike
    if contract_strike is None:
        return False
    return abs(float(contract_strike) - float(strike)) < 1e-9


def _contract_expiry_sort_key(contract: Contract) -> tuple[int, dt.date, str]:
    raw = (contract.lastTradeDateOrContractMonth or "").strip()
    expiry = parse_contract_expiry(raw)
    if expiry is None:
        return (1, dt.date.max, raw)
    return (0, expiry, raw)


def _dedupe_by_con_id(contracts: Iterable[Contract]) -> list[Contract]:
    seen: set[int] = set()
    result: list[Contract] = []
    for contract in contracts:
        con_id = contract.conId
        if not con_id or con_id in seen:
            continue
        seen.add(con_id)
        result.append(contract)
    return result


def _qualify_contracts(ib: IB, spec: Contract) -> Contract:
    # ib.qualifyContracts mutates the provided Contract in place; return that same
    # single qualified Contract for downstream use.
    ib.qualifyContracts(spec)
    return spec


def _request_contracts(ib: IB, spec: Contract) -> list[Contract]:
    details = ib.reqContractDetails(spec)
    contracts: list[Contract] = []
    for detail in details:
        contract = getattr(detail, "contract", None)
        if isinstance(contract, Contract) and contract.conId and contract.conId != 0:
            contracts.append(contract)
    return _dedupe_by_con_id(contracts)


def _chain_attr(chain: Any, key: str) -> Any:
    if isinstance(chain, dict):
        return chain.get(key)
    return getattr(chain, key, None)


def _to_str_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, set):
        return {str(item) for item in value}
    if isinstance(value, list | tuple):
        return {str(item) for item in value}
    return {str(value)}


def _to_float_list(value: Any) -> list[float]:
    if value is None:
        return []
    items: list[Any]
    if isinstance(value, list | tuple | set):
        items = list(value)
    else:
        items = [value]
    result: list[float] = []
    for item in items:
        try:
            result.append(float(item))
        except (TypeError, ValueError):
            continue
    return result


def _month_key(contract_month: str | None) -> str | None:
    if contract_month is None:
        return None
    return contract_month.replace("-", "")


def _expiry_matches_month(expiry: str, contract_month: str | None) -> bool:
    month_key = _month_key(contract_month)
    if month_key is None:
        return True
    cleaned = expiry.strip()
    return cleaned.startswith(month_key)


def _pick_underlying_future_contract(ib: IB, request: ContractSelectionRequest) -> Contract:
    spec = Contract(
        symbol=request.symbol,
        secType="FUT",
        exchange=request.exchange,
        currency=request.currency,
    )
    ib_contract_month = _normalize_contract_month(request.contract_month)
    if ib_contract_month is not None:
        spec.lastTradeDateOrContractMonth = ib_contract_month

    contracts = _request_contracts(ib, spec)
    contracts = [contract for contract in contracts if _contract_month_matches(contract, request.contract_month)]
    contracts = sorted(contracts, key=_contract_expiry_sort_key)
    if not contracts:
        context = _build_lookup_context(request)
        raise RuntimeError(f"No underlying futures contract found for {context} while selecting FOP.")
    return contracts[0]


def _build_lookup_context(request: ContractSelectionRequest) -> str:
    return (
        f"{request.symbol} {request.sec_type} on {request.exchange}"
        + (f" month={request.contract_month}" if request.contract_month else "")
        + (f" strike={request.strike}" if request.strike is not None else "")
        + (f" right={request.right}" if request.right else "")
    )


def _describe_contract(contract: Contract) -> str:
    raw_expiry = (contract.lastTradeDateOrContractMonth or "").strip() or "unknown"
    return (
        f"con_id={contract.conId}, local_symbol={contract.localSymbol or 'unknown'}, " f"expiry={raw_expiry}, strike={contract.strike}, right={contract.right}"
    )


class ContractSelector(ABC):
    """Product interface for sec_type-specific contract selectors."""

    @abstractmethod
    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        """Build the IBKR contract spec used for reqContractDetails."""

    def filter_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return contracts

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return contracts

    def validate_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> None:
        if not contracts:
            context = _build_lookup_context(request)
            raise RuntimeError(f"No contracts found for {context}. " "Check that the contract specification is correct.")

    def select(self, ib: IB, request: ContractSelectionRequest) -> tuple[Contract, int]:
        contracts = _request_contracts(ib, self.build_spec(request))
        contracts = self.filter_matches(contracts, request)
        contracts = self.sort_matches(contracts, request)
        self.validate_matches(contracts, request)
        return contracts[0], len(contracts)


class StockContractSelector(ContractSelector):
    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        return Contract(
            symbol=request.symbol,
            secType="STK",
            exchange=request.exchange,
            currency=request.currency,
        )

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return sorted(
            contracts,
            key=lambda contract: (contract.primaryExchange or "", contract.conId),
        )


class IndexContractSelector(ContractSelector):
    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        return Contract(
            symbol=request.symbol,
            secType="IND",
            exchange=request.exchange,
            currency=request.currency,
        )

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return sorted(
            contracts,
            key=lambda contract: (contract.exchange or "", contract.conId),
        )


class FutureContractSelector(ContractSelector):
    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        spec = Contract(
            symbol=request.symbol,
            secType="FUT",
            exchange=request.exchange,
            currency=request.currency,
        )
        ib_contract_month = _normalize_contract_month(request.contract_month)
        if ib_contract_month is not None:
            spec.lastTradeDateOrContractMonth = ib_contract_month
        return spec

    def filter_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return [contract for contract in contracts if _contract_month_matches(contract, request.contract_month)]

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return sorted(contracts, key=_contract_expiry_sort_key)


class OptionContractSelector(ContractSelector):
    sec_type = "OPT"

    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        normalized_right = _normalize_right(request.right)
        spec = Contract(
            symbol=request.symbol,
            secType=self.sec_type,
            exchange=request.exchange,
            currency=request.currency,
        )
        ib_contract_month = _normalize_contract_month(request.contract_month)
        if ib_contract_month is not None:
            spec.lastTradeDateOrContractMonth = ib_contract_month
        if request.strike is not None:
            spec.strike = request.strike
        if normalized_right is not None:
            spec.right = normalized_right
        return spec

    def filter_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        normalized_right = _normalize_right(request.right)
        return [
            contract
            for contract in contracts
            if _contract_month_matches(contract, request.contract_month)
            and _strike_matches(contract, request.strike)
            and _option_right_matches(contract, normalized_right)
        ]

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return sorted(
            contracts,
            key=lambda contract: (
                *_contract_expiry_sort_key(contract),
                float(contract.strike or 0.0),
                contract.right or "",
            ),
        )

    def validate_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> None:
        super().validate_matches(contracts, request)
        if len(contracts) > 1:
            context = _build_lookup_context(request)
            candidates = "; ".join(_describe_contract(contract) for contract in contracts[:5])
            raise RuntimeError(
                f"Ambiguous option selection for {context}. "
                f"Found {len(contracts)} matches. Top candidates: {candidates}. "
                "Provide contract_month, strike, and right to select one contract."
            )


class FutureOptionContractSelector(ContractSelector):
    sec_type = "FOP"

    def build_spec(self, request: ContractSelectionRequest) -> Contract:
        raise NotImplementedError("FutureOptionContractSelector uses select() with IB-dependent chain lookup.")

    def select(self, ib: IB, request: ContractSelectionRequest) -> tuple[Contract, int]:
        spec = self._build_fop_spec(ib, request)
        _qualify_contracts(ib, spec)
        if spec.conId is None:
            raise RuntimeError(f"No FOP contract found for {_build_lookup_context(request)}.")
        return spec, 1

    def _build_fop_spec(self, ib: IB, request: ContractSelectionRequest) -> Contract:
        index = Index(
            request.symbol,
            request.exchange,
            currency=request.currency,
        )
        ib.qualifyContracts(index)

        chains = ib.reqSecDefOptParams(
            underlyingSymbol=index.symbol,
            futFopExchange=index.exchange,
            underlyingSecType=index.secType,
            underlyingConId=index.conId,
        )

        if not chains:
            context = _build_lookup_context(request)
            raise RuntimeError(f"No FOP option chain metadata found for {context} " f"(underlying_con_id={index.conId}).")

        candidate_chains = self._filter_chain_candidates(chains, request)
        selected_chain = self._select_chain(candidate_chains)
        expirations = self._collect_expirations(candidate_chains)
        strikes = self._collect_strikes(candidate_chains)
        self._validate_chain(expirations, strikes, request)

        normalized_right = _normalize_right(request.right)
        spec = Contract(
            symbol=request.symbol,
            secType=self.sec_type,
            exchange=request.exchange,
            currency=request.currency,
        )
        ib_contract_month = _normalize_contract_month(request.contract_month)
        if ib_contract_month is not None:
            spec.lastTradeDateOrContractMonth = ib_contract_month
        if request.strike is not None:
            spec.strike = request.strike
        if normalized_right is not None:
            spec.right = normalized_right

        trading_class = _chain_attr(selected_chain, "tradingClass")
        if isinstance(trading_class, str) and trading_class.strip():
            spec.tradingClass = trading_class.strip()
        multiplier = _chain_attr(selected_chain, "multiplier")
        if multiplier is not None and str(multiplier).strip():
            spec.multiplier = str(multiplier).strip()

        return spec

    def filter_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        normalized_right = _normalize_right(request.right)
        return [
            contract
            for contract in contracts
            if _contract_month_matches(contract, request.contract_month)
            and _strike_matches(contract, request.strike)
            and _option_right_matches(contract, normalized_right)
        ]

    def sort_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> list[Contract]:
        return sorted(
            contracts,
            key=lambda contract: (
                *_contract_expiry_sort_key(contract),
                float(contract.strike or 0.0),
                contract.right or "",
            ),
        )

    def validate_matches(self, contracts: list[Contract], request: ContractSelectionRequest) -> None:
        super().validate_matches(contracts, request)
        if len(contracts) > 1:
            context = _build_lookup_context(request)
            candidates = "; ".join(_describe_contract(contract) for contract in contracts[:5])
            raise RuntimeError(
                f"Ambiguous option selection for {context}. "
                f"Found {len(contracts)} matches. Top candidates: {candidates}. "
                "Provide contract_month, strike, and right to select one contract."
            )

    def _filter_chain_candidates(self, chains: list[Any], request: ContractSelectionRequest) -> list[Any]:
        exchange_key = request.exchange.upper()
        candidates = [chain for chain in chains if str(_chain_attr(chain, "exchange") or "").upper() == exchange_key]
        if not candidates:
            candidates = list(chains)

        if request.contract_month is not None:
            month_filtered = [
                chain
                for chain in candidates
                if any(_expiry_matches_month(expiry, request.contract_month) for expiry in _to_str_set(_chain_attr(chain, "expirations")))
            ]
            if month_filtered:
                candidates = month_filtered

        if request.strike is not None:
            strike_filtered = [
                chain
                for chain in candidates
                if any(abs(option_strike - request.strike) < 1e-9 for option_strike in _to_float_list(_chain_attr(chain, "strikes")))
            ]
            if strike_filtered:
                candidates = strike_filtered

        return candidates

    def _select_chain(self, chains: list[Any]) -> Any:
        def _sort_key(chain: Any) -> tuple[int, int, str]:
            trading_class = str(_chain_attr(chain, "tradingClass") or "").strip().upper()
            is_weekly = 1 if trading_class.startswith("WL") else 0
            strike_count = len(_to_float_list(_chain_attr(chain, "strikes")))
            return (is_weekly, -strike_count, trading_class)

        candidates = sorted(chains, key=_sort_key)
        return candidates[0]

    def _collect_expirations(self, chains: list[Any]) -> set[str]:
        expirations: set[str] = set()
        for chain in chains:
            expirations.update(_to_str_set(_chain_attr(chain, "expirations")))
        return expirations

    def _collect_strikes(self, chains: list[Any]) -> list[float]:
        strikes: set[float] = set()
        for chain in chains:
            strikes.update(_to_float_list(_chain_attr(chain, "strikes")))
        return sorted(strikes)

    def _validate_chain(
        self,
        expirations: set[str],
        strikes: list[float],
        request: ContractSelectionRequest,
    ) -> None:
        if request.contract_month is not None:
            if not any(_expiry_matches_month(expiry, request.contract_month) for expiry in expirations):
                sample = ", ".join(sorted(expirations)[:10]) or "none"
                raise RuntimeError(
                    f"No FOP expirations matching month={request.contract_month} "
                    f"for {request.symbol} on {request.exchange}. "
                    f"Available expirations: {sample}."
                )
        if request.strike is not None:
            strike_found = any(abs(option_strike - request.strike) < 1e-9 for option_strike in strikes)
            if not strike_found:
                sample = ", ".join(str(value) for value in sorted(set(strikes))[:20])
                raise RuntimeError(f"No FOP strike={request.strike} for {request.symbol} on {request.exchange}. " f"Available strikes: {sample or 'none'}.")


class ContractSelectorFactory:
    """Factory Method creator for contract selectors."""

    _selector_types: dict[str, type[ContractSelector]] = {
        "STK": StockContractSelector,
        "IND": IndexContractSelector,
        "FUT": FutureContractSelector,
        "OPT": OptionContractSelector,
        "FOP": FutureOptionContractSelector,
    }

    @classmethod
    def create(cls, sec_type: str) -> ContractSelector:
        key = sec_type.upper()
        selector_type = cls._selector_types.get(key)
        if selector_type is None:
            raise ValueError(f"Unsupported sec_type '{sec_type}'.")
        return selector_type()


def select_contract_for_watchlist(
    ib: IB,
    symbol: str,
    sec_type: str,
    exchange: str,
    contract_month: str | None = None,
    strike: float | None = None,
    right: str | None = None,
) -> tuple[Contract, int]:
    normalized_contract_month = normalize_contract_month_input(contract_month)
    request = ContractSelectionRequest(
        symbol=symbol,
        sec_type=sec_type.upper(),
        exchange=exchange,
        contract_month=normalized_contract_month,
        strike=strike,
        right=right,
    )
    selector = ContractSelectorFactory.create(request.sec_type)
    return selector.select(ib, request)
