// Trade-group shapes: the search/picker row, the GET /trade-groups list row
// with its P&L split, and the Strategies workspace detail and executions
// payloads. See docs/design/strategies-and-trade-groups.md.

import type { TagChip } from "./tags";

export interface TradeGroupResult {
  id: number;
  account_id: number | null;
  name: string;
  status: string;
  primary_strategy_value: string | null;
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

// The list-endpoint row above plus the fields only the Strategies workspace
// needs. One source for the P&L shape, so the workspace and the Strategy P&L
// table cannot describe the same payload differently.
export type TradeGroup = TradeGroupPnlRow & {
  strategy_id?: number | null;
  tags?: TagChip[];
  open_task_count?: number;
  notes: string | null;
  meta_yaml: string | null;
  status: "open" | "closed" | "archived";
  opened_at: string;
  closed_at: string | null;
  opened_by: string | null;
  closed_by: string | null;
};

export type TradeGroupDetail = TradeGroup & {
  execution_count: number;
};

export type GroupExecution = {
  id: number;
  trade_id: number | null;
  account_id: number;
  account_alias: string | null;
  executed_at: string;
  side: string | null;
  quantity: number;
  price: number;
  commission: number | null;
  realized_pnl: number | null;
  exec_role: string;
  sec_type: string | null;
  contract_display: string | null;
  data_source: string;
  // IBKR FlexQuery trade codes (the `notes` attribute): A=assigned,
  // Ep=from expiration, Ex=exercise, P=partial, WS=wash sale, etc.
  ib_codes: string | null;
  // False for preemptively-tagged live fills not yet settled.
  settled?: boolean;
  multiplier?: number;
  // Signed qty × price × multiplier + commission (debit positive, credit
  // negative). Null on combo_summary rows so legs aren't double-counted.
  cost_basis?: number | null;
};

export type GroupOpenPosition = {
  account_id: number;
  account_alias: string | null;
  con_id: number;
  symbol: string | null;
  local_symbol: string | null;
  contract_display: string | null;
  sec_type: string | null;
  // Option contract detail (null for non-options / no settled snapshot yet).
  right: string | null;
  option_expiry_date: string | null;
  dte: number | null;
  strike: number | null;
  position: number;
  avg_cost: number;
  multiplier: string | null;
  mark_price: number | null;
  position_value: number | null;
  fifo_pnl_unrealized: number | null;
  as_of_date: string | null;
  // Intraday overlay (additive): live current-state fields.
  source: string;
  mark: number | null;
  mark_ts: string | null;
  live_unrealized: number | null;
  // Staleness of the live TWS overlay: true when the settled snapshot is newer
  // (prior-MT-day live snapshot). When stale, the live overlay cells are blanked
  // and the freshness badge reads "stale" (not green "live").
  live_fetched_at: string | null;
  live_is_stale: boolean;
  // Per-contract greeks from the live option-metrics sync (null for non-options
  // or when that job hasn't run). The table shows them scaled by position size.
  delta: number | null;
  gamma: number | null;
  // Per-contract implied volatility (decimal fraction) from the same live
  // option-metrics sync. Not scaled by position size; shown as a percent.
  iv: number | null;
};

export type GroupAccountPnl = {
  account_id: number;
  account_alias: string | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  intraday_unrealized_pnl: number | null;
  intraday_realized_pnl: number | null;
  intraday_total_pnl: number | null;
};

export type GroupExecutionsResponse = {
  trade_group_id: number;
  total_realized_pnl: number | null;
  total_unrealized_pnl: number | null;
  executions: GroupExecution[];
  open_positions: GroupOpenPosition[];
  // Intraday overlay (additive).
  intraday_unrealized_pnl: number | null;
  intraday_realized_pnl: number | null;
  intraday_total_pnl: number | null;
  marks_as_of: string | null;
  // Per-account breakdown (additive).
  by_account: GroupAccountPnl[];
};
