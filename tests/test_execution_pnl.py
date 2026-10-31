"""The one realized-PnL rule, and the row scoping each caller applies to it."""

from __future__ import annotations

from src.api.routers.trades import _trade_realized_pnl_from_executions
from src.services.execution_pnl import ExecutionPnlRow, realized_pnl_total
from src.services.trade_group_pnl import trade_group_realized_pnl


def _row(realized: float | None, exec_role: str, is_canonical: bool = True) -> ExecutionPnlRow:
    raw = None if realized is None else {"fifoPnlRealized": realized}
    return ExecutionPnlRow(raw=raw, exec_role=exec_role, is_canonical=is_canonical)


def test_plain_fills_are_summed() -> None:
    assert realized_pnl_total([_row(10.0, "standalone"), _row(-4.0, "standalone")]) == 6.0


def test_nothing_contributes_gives_none_not_zero() -> None:
    assert realized_pnl_total([]) is None
    assert realized_pnl_total([_row(None, "standalone")]) is None


def test_combo_summary_replaces_its_legs() -> None:
    rows = [_row(100.0, "combo_summary"), _row(70.0, "leg"), _row(30.0, "leg")]
    assert realized_pnl_total(rows) == 100.0


def test_standalone_fills_still_count_next_to_a_combo() -> None:
    """The case the trade and trade-group rules used to disagree on: a group
    holding a spread *and* an outright fill reports both."""
    rows = [_row(100.0, "combo_summary"), _row(70.0, "leg"), _row(5.0, "standalone")]
    assert realized_pnl_total(rows) == 105.0
    assert trade_group_realized_pnl(rows) == 105.0


def test_trade_scoping_drops_superseded_revisions() -> None:
    """A trade holds every revision of a fill; only the canonical one counts."""
    rows = [_row(10.0, "standalone", is_canonical=False), _row(12.0, "standalone", is_canonical=True)]
    assert _trade_realized_pnl_from_executions(rows) == 12.0
    assert _trade_realized_pnl_from_executions([_row(10.0, "standalone", is_canonical=False)]) is None


def test_trade_and_group_agree_on_a_pure_combo_or_pure_outright_trade() -> None:
    combo = [_row(100.0, "combo_summary"), _row(70.0, "leg"), _row(30.0, "leg")]
    outright = [_row(10.0, "standalone"), _row(-4.0, "standalone")]
    for rows in (combo, outright):
        assert _trade_realized_pnl_from_executions(rows) == trade_group_realized_pnl(rows)
