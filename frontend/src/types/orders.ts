// Order rows. Mirrors OrderResponse in src/api/routers/orders.py; the same
// shape arrives over SSE on the "orders" topic.

export interface Order {
  id: number;
  account_id: number;
  account_alias: string | null;
  symbol: string;
  sec_type: string;
  exchange: string;
  currency: string;
  side: string;
  quantity: number;
  order_type: string;
  limit_price: number | null;
  tif: string;
  status: string;
  source: string;
  con_id: number | null;
  local_symbol: string | null;
  trading_class: string | null;
  contract_month: string | null;
  contract_expiry: string | null;
  option_right: string | null;
  option_strike: string | null;
  contract_display_name: string;
  ib_order_id: number | null;
  ib_perm_id: number | null;
  filled_quantity: number;
  avg_fill_price: number | null;
  last_error: string | null;
  request_text: string | null;
  submitted_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}
