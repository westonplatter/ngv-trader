"""Self-contained tests for the `meta_yaml` API surface on trade groups.

Covers the new validation helper and request/response schema fields added to
`src/api/routers/trade_groups.py`. No DB connection required — these exercise
pure functions and Pydantic models directly. Run with:

    uv run python scripts/test_trade_groups_meta_api.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from fastapi import HTTPException

from src.api.routers.trade_groups import (
    TradeGroupCreateRequest,
    TradeGroupDetailResponse,
    TradeGroupPatchRequest,
    TradeGroupResponse,
    _parse_meta_or_400,
)

_NOW = datetime(2026, 6, 12, 14, 31, tzinfo=timezone.utc)


def _base_response_kwargs() -> dict:
    return {
        "id": 1,
        "account_id": None,
        "name": "GLD covered call",
        "notes": None,
        "status": "open",
        "primary_strategy_value": None,
        "opened_at": _NOW,
        "closed_at": None,
        "opened_by": "api",
        "closed_by": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


# -- _parse_meta_or_400 ------------------------------------------------------


def test_parse_meta_or_400_none_returns_none() -> None:
    assert _parse_meta_or_400(None) is None


def test_parse_meta_or_400_empty_string_returns_none() -> None:
    assert _parse_meta_or_400("") is None


def test_parse_meta_or_400_valid_yaml_returns_dict() -> None:
    result = _parse_meta_or_400("targets:\n  delta:\n    target: 100\n")
    assert result == {"targets": {"delta": {"target": 100}}}


def test_parse_meta_or_400_invalid_yaml_raises_http_400() -> None:
    try:
        _parse_meta_or_400("targets: [unclosed")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "Invalid YAML" in exc.detail
    else:
        raise AssertionError("expected HTTPException")


def test_parse_meta_or_400_malformed_block_raises_http_400() -> None:
    try:
        _parse_meta_or_400("targets:\n  delta:\n    target: not_a_number\n")
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "targets.delta.target" in exc.detail
    else:
        raise AssertionError("expected HTTPException")


def test_parse_meta_or_400_preserves_underlying_message() -> None:
    from src.services.trade_group_meta import TradeGroupMetaError, parse_meta_yaml

    bad_yaml = "profit_targets:\n  - amount: 'lots'\n"
    try:
        parse_meta_yaml(bad_yaml)
        raise AssertionError("expected TradeGroupMetaError from parse_meta_yaml")
    except TradeGroupMetaError as direct_exc:
        expected_message = str(direct_exc)

    try:
        _parse_meta_or_400(bad_yaml)
    except HTTPException as http_exc:
        assert http_exc.detail == expected_message
    else:
        raise AssertionError("expected HTTPException")


# -- TradeGroupCreateRequest --------------------------------------------------


def test_create_request_meta_yaml_defaults_to_none() -> None:
    body = TradeGroupCreateRequest(name="x")
    assert body.meta_yaml is None


def test_create_request_meta_yaml_accepts_string() -> None:
    body = TradeGroupCreateRequest(name="x", meta_yaml="thesis: test\n")
    assert body.meta_yaml == "thesis: test\n"


# -- TradeGroupPatchRequest ---------------------------------------------------


def test_patch_request_meta_yaml_defaults_to_none() -> None:
    body = TradeGroupPatchRequest()
    assert body.meta_yaml is None


def test_patch_request_meta_yaml_accepts_empty_string_to_clear() -> None:
    # An explicit empty string (distinct from omitted/None) signals "clear the spec".
    body = TradeGroupPatchRequest(meta_yaml="")
    assert body.meta_yaml == ""


def test_patch_request_meta_yaml_accepts_string() -> None:
    body = TradeGroupPatchRequest(meta_yaml="dates:\n  entry_estimate: 2026-06-12\n")
    assert body.meta_yaml == "dates:\n  entry_estimate: 2026-06-12\n"


# -- TradeGroupResponse -------------------------------------------------------


def test_response_meta_yaml_defaults_to_none() -> None:
    resp = TradeGroupResponse(**_base_response_kwargs())
    assert resp.meta_yaml is None


def test_response_meta_yaml_round_trips_raw_string() -> None:
    raw = "targets:\n  delta:\n    target: 120\n"
    resp = TradeGroupResponse(**_base_response_kwargs(), meta_yaml=raw)
    assert resp.meta_yaml == raw


# -- TradeGroupDetailResponse --------------------------------------------------


def test_detail_response_meta_defaults_to_none() -> None:
    resp = TradeGroupDetailResponse(**_base_response_kwargs(), tags=[], execution_count=0)
    assert resp.meta is None


def test_detail_response_meta_holds_parsed_dict() -> None:
    raw = "targets:\n  delta:\n    target: 120\n"
    parsed = _parse_meta_or_400(raw)
    resp = TradeGroupDetailResponse(
        **_base_response_kwargs(),
        meta_yaml=raw,
        tags=[],
        execution_count=0,
        meta=parsed,
    )
    assert resp.meta_yaml == raw
    assert resp.meta == {"targets": {"delta": {"target": 120}}}


def test_detail_response_meta_none_when_meta_yaml_none() -> None:
    resp = TradeGroupDetailResponse(
        **_base_response_kwargs(),
        meta_yaml=None,
        tags=[],
        execution_count=0,
        meta=_parse_meta_or_400(None),
    )
    assert resp.meta_yaml is None
    assert resp.meta is None


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