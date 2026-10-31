// Position rows from GET /positions: the settled FlexQuery snapshot plus the
// additive live TWS overlay and option metrics.

import type { TagChip } from "./tags";

export interface TradeGroupRef {
  id: number;
  name: string;
}

export interface Position {
  id: number;
  account_id: number;
  account_alias: string;
  contract_display_name: string;
  con_id: number;
  trade_groups: TradeGroupRef[];
  symbol: string | null;
  sec_type: string | null;
  exchange: string | null;
  primary_exchange: string | null;
  currency: string | null;
  local_symbol: string | null;
  trading_class: string | null;
  last_trade_date: string | null;
  option_expiry_date: string | null;
  dte: number | null;
  strike: number | null;
  right: string | null;
  multiplier: string | null;
  position: number;
  avg_cost: number;
  mark_price: number | null;
  position_value: number | null;
  fifo_pnl_unrealized: number | null;
  fetched_at: string;
  // Intraday overlay (additive): live current-state fields.
  source: string;
  mark: number | null;
  mark_ts: string | null;
  live_unrealized: number | null;
  // Staleness of the live TWS overlay: true when the settled FlexQuery snapshot
  // was loaded more recently than the live snapshot. When stale, the overlay
  // columns are blanked and the freshness badge reads "stale" (not green "live").
  live_fetched_at: string | null;
  live_is_stale: boolean;
  // Live option metrics (additive; from the separate option-metrics sync job).
  // null for non-options or when that job hasn't run.
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  und_price: number | null;
  intrinsic_value: number | null;
  extrinsic_value: number | null;
  // Free-form tags on (account, contract) and its not-done task count.
  tags?: TagChip[];
  open_task_count?: number;
}
