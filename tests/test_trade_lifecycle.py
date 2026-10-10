"""Open/Close/Roll labelling for combo (BAG) trades, derived from their legs."""

from src.api.routers.trades import _combo_lifecycle, _trade_lifecycle_from_execution


def _leg(indicator: str, *, canonical: bool = True) -> tuple[dict, str, bool]:
    return ({"openCloseIndicator": indicator}, "leg", canonical)


def test_vertical_spread_opening_both_legs_is_open() -> None:
    # e.g. buy CL 85 call / sell CL 95 call — a new call spread, not a roll.
    executions = [({}, "combo_summary", True), _leg("O"), _leg("O")]
    assert _trade_lifecycle_from_execution({}, "combo_summary", executions) == "Open"


def test_combo_closing_both_legs_is_close() -> None:
    executions = [({}, "combo_summary", True), _leg("C"), _leg("C")]
    assert _trade_lifecycle_from_execution({}, "combo_summary", executions) == "Close"


def test_combo_closing_one_leg_and_opening_another_is_roll() -> None:
    executions = [({}, "combo_summary", True), _leg("C"), _leg("O")]
    assert _trade_lifecycle_from_execution({}, "combo_summary", executions) == "Roll"


def test_non_canonical_legs_are_ignored() -> None:
    executions = [_leg("O"), _leg("C", canonical=False)]
    assert _trade_lifecycle_from_execution({}, "combo_summary", executions) == "Open"


def test_combo_without_leg_indicators_is_unlabelled() -> None:
    assert _trade_lifecycle_from_execution({}, "combo_summary", []) is None
    assert _combo_lifecycle([None, None]) is None


def test_standalone_fill_reads_its_own_indicator() -> None:
    assert _trade_lifecycle_from_execution({"openCloseIndicator": "C"}, "standalone") == "Close"
