"""Self-contained tests for trade-group meta YAML parsing/validation.

No DB or IBKR connection required. Run with:

    uv run python scripts/test_trade_group_meta.py
"""

from __future__ import annotations

import datetime as dt
import sys

from src.services.trade_group_meta import (
    RECOGNIZED_TOP_LEVEL_KEYS,
    TradeGroupMetaError,
    _jsonify,
    parse_meta_yaml,
)


def _assert_raises(callable_, *args, **kwargs) -> TradeGroupMetaError:
    try:
        callable_(*args, **kwargs)
    except TradeGroupMetaError as exc:
        return exc
    raise AssertionError(f"expected TradeGroupMetaError, none raised (args={args!r})")


# -- empty/blank input ---------------------------------------------------------


def test_parse_none() -> None:
    assert parse_meta_yaml(None) is None


def test_parse_empty_string() -> None:
    assert parse_meta_yaml("") is None


def test_parse_whitespace_only() -> None:
    assert parse_meta_yaml("   \n\t  ") is None


def test_parse_yaml_null_document() -> None:
    # A YAML document that parses to `None` (e.g. just comments) is also empty.
    assert parse_meta_yaml("# just a comment\n") is None


# -- top-level shape ------------------------------------------------------------


def test_top_level_must_be_mapping_list() -> None:
    exc = _assert_raises(parse_meta_yaml, "- 1\n- 2\n")
    assert "mapping" in str(exc)


def test_top_level_must_be_mapping_scalar() -> None:
    exc = _assert_raises(parse_meta_yaml, "just a string")
    assert "mapping" in str(exc)


def test_invalid_yaml_syntax_raises() -> None:
    exc = _assert_raises(parse_meta_yaml, "targets: [unclosed")
    assert "Invalid YAML" in str(exc)


def test_unknown_top_level_keys_pass_through() -> None:
    result = parse_meta_yaml("thesis: gold consolidating\ncustom_field: 42\n")
    assert result == {"thesis": "gold consolidating", "custom_field": 42}


def test_recognized_top_level_keys_constant() -> None:
    assert RECOGNIZED_TOP_LEVEL_KEYS == {"targets", "dates", "profit_targets"}


# -- targets.delta --------------------------------------------------------------


def test_targets_delta_full_valid() -> None:
    raw = """
targets:
  delta:
    target: 120
    min: 90
    max: 150
    tolerance: 10
    static: 200
    options_transient: -80
"""
    result = parse_meta_yaml(raw)
    assert result["targets"]["delta"] == {
        "target": 120,
        "min": 90,
        "max": 150,
        "tolerance": 10,
        "static": 200,
        "options_transient": -80,
    }


def test_targets_absent_is_fine() -> None:
    assert parse_meta_yaml("thesis: no targets here\n") == {"thesis": "no targets here"}


def test_targets_delta_absent_is_fine() -> None:
    result = parse_meta_yaml("targets: {}\n")
    assert result == {"targets": {}}


def test_targets_must_be_mapping() -> None:
    exc = _assert_raises(parse_meta_yaml, "targets: [1, 2, 3]\n")
    assert "`targets` must be a mapping" in str(exc)


def test_targets_delta_must_be_mapping() -> None:
    exc = _assert_raises(parse_meta_yaml, "targets:\n  delta: [1, 2]\n")
    assert "`targets.delta` must be a mapping" in str(exc)


def test_targets_delta_field_must_be_number_string() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "targets:\n  delta:\n    target: not_a_number\n",
    )
    assert "targets.delta.target" in str(exc)
    assert "must be a number" in str(exc)


def test_targets_delta_rejects_booleans() -> None:
    # bool is a subclass of int; explicitly rejected so `true` isn't read as 1.
    exc = _assert_raises(
        parse_meta_yaml,
        "targets:\n  delta:\n    target: true\n",
    )
    assert "must be a number" in str(exc)


def test_targets_delta_accepts_floats() -> None:
    result = parse_meta_yaml("targets:\n  delta:\n    target: 12.5\n")
    assert result["targets"]["delta"]["target"] == 12.5


def test_targets_delta_partial_fields_ok() -> None:
    result = parse_meta_yaml("targets:\n  delta:\n    target: 100\n")
    assert result["targets"]["delta"] == {"target": 100}


def test_targets_delta_unrecognized_field_passes_through() -> None:
    result = parse_meta_yaml("targets:\n  delta:\n    target: 100\n    note: extra\n")
    assert result["targets"]["delta"]["note"] == "extra"


def test_targets_delta_null_field_ok() -> None:
    # explicit null present in mapping should be treated as "not present" for validation
    result = parse_meta_yaml("targets:\n  delta:\n    target: null\n")
    assert result["targets"]["delta"]["target"] is None


# -- dates ------------------------------------------------------------------


def test_dates_iso_strings() -> None:
    raw = """
dates:
  entry_estimate: '2026-06-12'
  exit_estimate: '2026-09-19'
"""
    result = parse_meta_yaml(raw)
    assert result["dates"]["entry_estimate"] == "2026-06-12"
    assert result["dates"]["exit_estimate"] == "2026-09-19"


def test_dates_native_yaml_date_becomes_iso_string() -> None:
    # Unquoted YYYY-MM-DD is parsed by PyYAML into a native `date` object.
    raw = "dates:\n  entry_estimate: 2026-06-12\n"
    result = parse_meta_yaml(raw)
    assert result["dates"]["entry_estimate"] == "2026-06-12"
    assert isinstance(result["dates"]["entry_estimate"], str)


def test_dates_absent_is_fine() -> None:
    result = parse_meta_yaml("dates: {}\n")
    assert result == {"dates": {}}


def test_dates_null_field_is_fine() -> None:
    result = parse_meta_yaml("dates:\n  entry_estimate: null\n")
    assert result["dates"]["entry_estimate"] is None


def test_dates_must_be_mapping() -> None:
    exc = _assert_raises(parse_meta_yaml, "dates: [1, 2]\n")
    assert "`dates` must be a mapping" in str(exc)


def test_dates_invalid_string_raises() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "dates:\n  entry_estimate: 'not-a-date'\n",
    )
    assert "dates.entry_estimate" in str(exc)
    assert "ISO date" in str(exc)


def test_dates_invalid_type_raises() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "dates:\n  entry_estimate: [2026, 6, 12]\n",
    )
    assert "ISO date" in str(exc)


def test_dates_whitespace_trimmed() -> None:
    result = parse_meta_yaml("dates:\n  entry_estimate: '  2026-06-12  '\n")
    assert result["dates"]["entry_estimate"] == "2026-06-12"


def test_dates_unrecognized_key_passes_through() -> None:
    result = parse_meta_yaml("dates:\n  entry_estimate: '2026-06-12'\n  custom: yes\n")
    assert result["dates"]["custom"] is True


# -- profit_targets ----------------------------------------------------------


def test_profit_targets_full_valid() -> None:
    raw = """
profit_targets:
  - date: '2026-08-15'
    amount: 1500
    note: roll up calls if realized+unrealized clears this
  - date: '2026-09-19'
    amount: 3200
"""
    result = parse_meta_yaml(raw)
    assert len(result["profit_targets"]) == 2
    assert result["profit_targets"][0] == {
        "date": "2026-08-15",
        "amount": 1500,
        "note": "roll up calls if realized+unrealized clears this",
    }
    assert result["profit_targets"][1] == {"date": "2026-09-19", "amount": 3200}


def test_profit_targets_absent_is_fine() -> None:
    assert parse_meta_yaml("thesis: x\n") == {"thesis": "x"}


def test_profit_targets_empty_list_is_fine() -> None:
    result = parse_meta_yaml("profit_targets: []\n")
    assert result == {"profit_targets": []}


def test_profit_targets_must_be_list() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "profit_targets:\n  date: '2026-08-15'\n  amount: 1500\n",
    )
    assert "`profit_targets` must be a list" in str(exc)


def test_profit_targets_item_must_be_mapping() -> None:
    exc = _assert_raises(parse_meta_yaml, "profit_targets:\n  - 1500\n")
    assert "profit_targets[0]" in str(exc)
    assert "must be a mapping" in str(exc)


def test_profit_targets_item_date_invalid() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "profit_targets:\n  - date: 'not-a-date'\n    amount: 100\n",
    )
    assert "profit_targets[0].date" in str(exc)


def test_profit_targets_item_amount_must_be_number() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "profit_targets:\n  - amount: 'a lot'\n",
    )
    assert "profit_targets[0].amount" in str(exc)
    assert "must be a number" in str(exc)


def test_profit_targets_item_amount_rejects_booleans() -> None:
    exc = _assert_raises(
        parse_meta_yaml,
        "profit_targets:\n  - amount: false\n",
    )
    assert "must be a number" in str(exc)


def test_profit_targets_item_missing_date_is_fine() -> None:
    result = parse_meta_yaml("profit_targets:\n  - amount: 500\n")
    assert result["profit_targets"] == [{"amount": 500}]


def test_profit_targets_item_missing_amount_is_fine() -> None:
    result = parse_meta_yaml("profit_targets:\n  - date: '2026-08-15'\n")
    assert result["profit_targets"] == [{"date": "2026-08-15"}]


def test_profit_targets_native_date_becomes_iso_string() -> None:
    raw = "profit_targets:\n  - date: 2026-08-15\n    amount: 1500\n"
    result = parse_meta_yaml(raw)
    assert result["profit_targets"][0]["date"] == "2026-08-15"
    assert isinstance(result["profit_targets"][0]["date"], str)


def test_profit_targets_error_index_reported() -> None:
    # Second item (index 1) is bad; error should point at index 1, not 0.
    exc = _assert_raises(
        parse_meta_yaml,
        "profit_targets:\n  - amount: 100\n  - amount: 'bad'\n",
    )
    assert "profit_targets[1].amount" in str(exc)


# -- combined / real-world example -------------------------------------------


def test_full_example_from_docs() -> None:
    raw = """
# GLD covered call: 200 long shares overwritten with calls. Steer net delta toward 120.
targets:
  delta:
    target: 120
    tolerance: 10
    static: 200            # from the 200 long shares
    options_transient: -80 # from the short calls, moves with the market
dates:
  entry_estimate: 2026-06-12
  exit_estimate: 2026-09-19
profit_targets:
  - date: 2026-08-15
    amount: 1500
    note: roll up calls if realized+unrealized clears this
thesis: gold consolidating; collect theta while range-bound   # arbitrary passthrough
"""
    result = parse_meta_yaml(raw)
    assert result["targets"]["delta"]["target"] == 120
    assert result["targets"]["delta"]["tolerance"] == 10
    assert result["targets"]["delta"]["static"] == 200
    assert result["targets"]["delta"]["options_transient"] == -80
    assert result["dates"]["entry_estimate"] == "2026-06-12"
    assert result["dates"]["exit_estimate"] == "2026-09-19"
    assert result["profit_targets"][0]["date"] == "2026-08-15"
    assert result["profit_targets"][0]["amount"] == 1500
    assert result["thesis"] == "gold consolidating; collect theta while range-bound"


def test_comments_and_ordering_do_not_affect_parse() -> None:
    # Comments are stripped by the YAML parser; only structure/values matter here
    # (raw source round-trip verbatim is the caller's responsibility, not this
    # module's — this module only produces the parsed/JSON view).
    raw_with_comments = "targets:\n  delta:\n    target: 100 # comment\n"
    raw_without_comments = "targets:\n  delta:\n    target: 100\n"
    assert parse_meta_yaml(raw_with_comments) == parse_meta_yaml(raw_without_comments)


# -- _jsonify (private helper, exercised directly for edge cases) -----------


def test_jsonify_scalars_unchanged() -> None:
    assert _jsonify(1) == 1
    assert _jsonify(1.5) == 1.5
    assert _jsonify("x") == "x"
    assert _jsonify(True) is True
    assert _jsonify(None) is None


def test_jsonify_date_and_datetime() -> None:
    assert _jsonify(dt.date(2026, 6, 12)) == "2026-06-12"
    assert _jsonify(dt.datetime(2026, 6, 12, 10, 30)) == "2026-06-12T10:30:00"


def test_jsonify_nested_dict_and_list() -> None:
    value = {"a": [dt.date(2026, 1, 1), {"b": dt.date(2026, 2, 2)}]}
    assert _jsonify(value) == {"a": ["2026-01-01", {"b": "2026-02-02"}]}


def test_jsonify_tuple_becomes_list() -> None:
    assert _jsonify((1, 2, 3)) == [1, 2, 3]


def test_jsonify_non_string_keys_stringified() -> None:
    assert _jsonify({1: "a"}) == {"1": "a"}


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