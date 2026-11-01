// Pricing page payloads: saved structures (GET/POST/PUT /structures), the
// futures term structure and option chain catalog (GET /futures/{sym}/...),
// and the expected-P&L response from the pricing service.

export type LegType = "c" | "p" | "d1" | "cash";

export interface SavedLeg {
  optionType: LegType;
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  tradePrice: number | null;
  bid: number | null;
  ask: number | null;
  undPrice: number | null;
  contractLabel: string;
  selectedConId: number | null;
  selectedExpiry: string | null;
  selectedTradingClass: string | null;
}

export interface SavedStructure {
  id: number;
  name: string;
  instrument: string;
  legs: SavedLeg[];
  spot_price: number | null;
  created_at: string;
  updated_at: string;
}

export interface FuturesContract {
  con_id: number;
  symbol: string;
  local_symbol: string;
  display_name: string;
  contract_expiry: string;
  contract_month: string;
  dte: number;
  bid: number | null;
  ask: number | null;
  last: number | null;
  close: number | null;
  volume: number | null;
  open_interest: number | null;
}

export interface ChainEntry {
  symbol: string;
  trading_class: string;
  expiration: string;
  strike: number;
  right: "C" | "P";
  dte: number;
  underlying_con_id: number;
  exchange: string;
  sec_type: string;
  con_id: number | null;
  display_name: string;
  is_monthly: boolean;
  bid: number | null;
  ask: number | null;
  last: number | null;
  iv: number | null;
  delta: number | null;
  und_price: number | null;
  observed_at: string | null;
}

export interface PnlRecord {
  spot_price: number;
  days_into_future: number;
  value: number;
}

export interface ModelOutputs {
  min_dte: number;
  pnl_records: PnlRecord[];
  pnl_records_count: number;
}

export interface ExpectedPnlResponse {
  model_inputs: Record<string, unknown>;
  model_outputs: ModelOutputs;
}
