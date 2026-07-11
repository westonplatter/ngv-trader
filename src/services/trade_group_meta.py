"""Parse and lightly validate the YAML "management spec" attached to a trade group.

The raw YAML authored by the operator (or an agent) is stored verbatim on
``TradeGroup.meta_yaml`` so it round-trips exactly. This module turns that source
into a JSON-serializable dict for the API and downstream agents.

Validation is intentionally *light*: a handful of recognized top-level blocks are
checked for shape so an agent can rely on their structure, while any other keys
pass through untouched. Recognized blocks:

- ``targets``: mapping of desired portfolio targets. ``targets.delta`` describes the
  aggregate (static stock + transient options) delta an agent should steer toward,
  e.g. ``target``/``min``/``max``/``tolerance``/``static``/``options_transient``.
- ``dates``: mapping of estimated lifecycle dates, e.g. ``entry_estimate`` /
  ``exit_estimate`` (ISO ``YYYY-MM-DD``).
- ``profit_targets``: list of ``{date, amount, note}`` checkpoints an agent can
  evaluate a position against over time.

Everything is optional. A block that is present but structurally wrong raises
``TradeGroupMetaError`` (surfaced by the API as a 400); a block that is absent is
simply skipped.
"""

from __future__ import annotations

import datetime as dt
from numbers import Real
from typing import Any

import yaml


class TradeGroupMetaError(ValueError):
    """Raised when meta YAML is invalid or a recognized block is malformed."""


RECOGNIZED_TOP_LEVEL_KEYS = frozenset({"targets", "dates", "profit_targets"})

# Numeric fields recognized inside ``targets.delta``. Others pass through.
_DELTA_NUMERIC_FIELDS = frozenset(
    {"target", "min", "max", "tolerance", "static", "options_transient"}
)
_DATE_FIELDS = frozenset({"entry_estimate", "exit_estimate"})


def parse_meta_yaml(raw: str | None) -> dict[str, Any] | None:
    """Parse raw YAML into a JSON-serializable dict, validating recognized blocks.

    Returns ``None`` for empty/blank input. Raises :class:`TradeGroupMetaError` on
    invalid YAML or a structurally invalid recognized block.
    """
    if raw is None or not raw.strip():
        return None
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise TradeGroupMetaError(f"Invalid YAML: {exc}") from exc
    if loaded is None:
        return None
    if not isinstance(loaded, dict):
        raise TradeGroupMetaError("Top-level meta must be a YAML mapping (key: value)")

    _validate_targets(loaded.get("targets"))
    _validate_dates(loaded.get("dates"))
    _validate_profit_targets(loaded.get("profit_targets"))

    return _jsonify(loaded)


def _validate_targets(targets: Any) -> None:
    if targets is None:
        return
    if not isinstance(targets, dict):
        raise TradeGroupMetaError("`targets` must be a mapping")
    delta = targets.get("delta")
    if delta is None:
        return
    if not isinstance(delta, dict):
        raise TradeGroupMetaError("`targets.delta` must be a mapping")
    for field in _DELTA_NUMERIC_FIELDS:
        _require_number_if_present(delta, field, f"targets.delta.{field}")


def _validate_dates(dates: Any) -> None:
    if dates is None:
        return
    if not isinstance(dates, dict):
        raise TradeGroupMetaError("`dates` must be a mapping")
    for field in _DATE_FIELDS:
        if field in dates and dates[field] is not None:
            _coerce_date(dates[field], f"dates.{field}")


def _validate_profit_targets(profit_targets: Any) -> None:
    if profit_targets is None:
        return
    if not isinstance(profit_targets, list):
        raise TradeGroupMetaError("`profit_targets` must be a list")
    for idx, item in enumerate(profit_targets):
        if not isinstance(item, dict):
            raise TradeGroupMetaError(f"`profit_targets[{idx}]` must be a mapping")
        if item.get("date") is not None:
            _coerce_date(item["date"], f"profit_targets[{idx}].date")
        _require_number_if_present(item, "amount", f"profit_targets[{idx}].amount")


def _require_number_if_present(mapping: dict[str, Any], key: str, path: str) -> None:
    value = mapping.get(key)
    # ``bool`` is a subclass of ``int``; reject it so ``true`` isn't read as 1.
    if value is not None and (isinstance(value, bool) or not isinstance(value, Real)):
        raise TradeGroupMetaError(f"`{path}` must be a number")


def _coerce_date(value: Any, path: str) -> dt.date:
    """Accept a native YAML date/datetime or an ISO ``YYYY-MM-DD`` string."""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError as exc:
            raise TradeGroupMetaError(
                f"`{path}` must be an ISO date (YYYY-MM-DD)"
            ) from exc
    raise TradeGroupMetaError(f"`{path}` must be an ISO date (YYYY-MM-DD)")


def _jsonify(value: Any) -> Any:
    """Recursively convert YAML-native scalars into JSON-serializable values.

    PyYAML parses ISO dates/timestamps into ``date``/``datetime`` objects, which are
    not JSON-serializable; normalize them to ISO strings so the parsed ``meta`` can be
    returned by the API as-is.
    """
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return value
