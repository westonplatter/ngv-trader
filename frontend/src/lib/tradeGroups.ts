// Shared trade-group shape and label helper used by the Trades and Positions
// tables and the trade-group search picker.

export interface TradeGroupResult {
  id: number;
  account_id: number | null;
  name: string;
  status: string;
  primary_strategy_value: string | null;
}

export function tradeGroupLabel(group: TradeGroupResult): string {
  const strategy = group.primary_strategy_value ?? "No Strategy";
  return `${strategy} > ${group.name}`;
}

// The full list-endpoint row, as returned by `GET /trade-groups`. The P&L split
// and instruments are populated only when the request opts in
// (`include_intraday=true`, or an `instrument` filter for the instruments);
// existing callers read `total_pnl` alone and see nulls in the rest.
export interface TradeGroupPnlRow extends TradeGroupResult {
  // Settled Total P&L: realized + settled unrealized. Never the overlay.
  total_pnl: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  // Intraday figures fold the live TWS overlay over the settled snapshot. With
  // no live data they equal the settled figures (graceful degradation).
  intraday_unrealized_pnl: number | null;
  intraday_realized_pnl: number | null;
  intraday_total_pnl: number | null;
  // Newest live mark behind this row, or null when nothing is live.
  marks_as_of: string | null;
  // True only when *every* live-sourced mark behind the row is stale.
  live_is_stale: boolean;
  // Underlying roots the group's executions touched, e.g. ["CL"].
  instruments: string[] | null;
}
