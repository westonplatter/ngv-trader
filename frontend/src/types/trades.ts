// Trade execution rows from GET /trade-executions: settled FlexQuery fills
// joined to their parent trade, plus unsettled live TWS fills.

import type { TagChip } from "./tags";

export interface TradeExecutionRow {
  id: number;
  trade_id: number | null;
  account_id: number;
  account_alias: string | null;
  ib_exec_id: string;
  exec_role: string;
  sec_type: string | null;
  executed_at: string;
  quantity: number;
  price: number;
  side: string | null;
  exchange: string | null;
  commission: number | null;
  realized_pnl: number | null;
  is_canonical: boolean;
  con_id: number | null;
  contract_display: string | null;
  parent_ib_exec_id: string | null;
  // IBKR FlexQuery trade codes (the `notes` attribute): A=assigned,
  // Ep=from expiration, Ex=exercise, P=partial, WS=wash sale, etc.
  ib_codes: string | null;
  data_source?: string;
  trade_ib_perm_id: number | null;
  trade_order_ref: string | null;
  trade_status: string;
  trade_lifecycle: string | null;
  trade_contract_display_name: string | null;
  trade_realized_pnl: number | null;
  trade_assigned_trade_group_id: number | null;
  trade_first_executed_at: string | null;
  trade_last_executed_at: string | null;
  // Unsettled TWS overlay: false for live fills not yet settled.
  settled?: boolean;
  live_trade_group_id?: number | null;
  // Free-form tags on the order (the trade once settled, else this live fill)
  // and its not-done task count.
  tags?: TagChip[];
  open_task_count?: number;
}

