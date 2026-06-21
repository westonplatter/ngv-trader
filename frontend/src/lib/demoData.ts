// Static demo fixtures used to render the UI without a live backend.
//
// Enabled via demo mode (see isDemoMode in ./demoMode). This lets us showcase
// the UI — and capture screenshots — with a representative book of positions:
//   - long 3 NQ futures contracts
//   - long ES future-option call diagonals
//   - long 200 GLD shares
//   - short 3 calls (ATM, OTM +2%, OTM +4%) against the GLD shares
//
// The shape mirrors PositionResponse from src/api/routers/positions.py so the
// fixtures flow through the real components unchanged.

export interface DemoTradeGroupRef {
  id: number;
  name: string;
}

export interface DemoPosition {
  id: number;
  account_alias: string;
  contract_display_name: string;
  con_id: number;
  trade_groups: DemoTradeGroupRef[];
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
}

const ACCOUNT = "DU1234567";
const FETCHED_AT = "2026-06-21T14:30:00Z";

// Trade groups the demo positions are assigned to. Names show up as links in
// the Positions table's "Trade Group" column.
const GROUP_NQ: DemoTradeGroupRef = { id: 101, name: "NQ Momentum" };
const GROUP_ES_DIAGONAL: DemoTradeGroupRef = { id: 102, name: "ES Call Diagonal" };
const GROUP_GLD_CC: DemoTradeGroupRef = { id: 103, name: "GLD Covered Calls" };

export const DEMO_POSITIONS: DemoPosition[] = [
  // ── Long 3 NQ futures contracts ────────────────────────────────────────────
  {
    id: 1,
    account_alias: ACCOUNT,
    contract_display_name: "NQ Sep'26 Future",
    con_id: 730283085,
    trade_groups: [GROUP_NQ],
    symbol: "NQ",
    sec_type: "FUT",
    exchange: "CME",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "NQU6",
    trading_class: "NQ",
    last_trade_date: "20260918",
    option_expiry_date: null,
    dte: 89,
    strike: null,
    right: null,
    multiplier: "20",
    position: 3,
    avg_cost: 21850.0,
    mark_price: 22010.25,
    position_value: 1320615.0,
    fifo_pnl_unrealized: 9615.0,
    fetched_at: FETCHED_AT,
  },

  // ── Long ES future-option call diagonal (long near + far calls) ─────────────
  {
    id: 2,
    account_alias: ACCOUNT,
    contract_display_name: "ES Jul'26 6000 Call",
    con_id: 651244012,
    trade_groups: [GROUP_ES_DIAGONAL],
    symbol: "ES",
    sec_type: "FOP",
    exchange: "CME",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "ESN6 C6000",
    trading_class: "ES",
    last_trade_date: "20260717",
    option_expiry_date: "20260717",
    dte: 26,
    strike: 6000.0,
    right: "C",
    multiplier: "50",
    position: 2,
    avg_cost: 4125.0,
    mark_price: 92.5,
    position_value: 9250.0,
    fifo_pnl_unrealized: 1000.0,
    fetched_at: FETCHED_AT,
  },
  {
    id: 3,
    account_alias: ACCOUNT,
    contract_display_name: "ES Sep'26 6100 Call",
    con_id: 651244089,
    trade_groups: [GROUP_ES_DIAGONAL],
    symbol: "ES",
    sec_type: "FOP",
    exchange: "CME",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "ESU6 C6100",
    trading_class: "ES",
    last_trade_date: "20260918",
    option_expiry_date: "20260918",
    dte: 89,
    strike: 6100.0,
    right: "C",
    multiplier: "50",
    position: 2,
    avg_cost: 7850.0,
    mark_price: 168.75,
    position_value: 16875.0,
    fifo_pnl_unrealized: 1175.0,
    fetched_at: FETCHED_AT,
  },

  // ── Long 200 GLD shares ─────────────────────────────────────────────────────
  {
    id: 4,
    account_alias: ACCOUNT,
    contract_display_name: "GLD Stock",
    con_id: 756733,
    trade_groups: [GROUP_GLD_CC],
    symbol: "GLD",
    sec_type: "STK",
    exchange: "SMART",
    primary_exchange: "ARCA",
    currency: "USD",
    local_symbol: "GLD",
    trading_class: "GLD",
    last_trade_date: null,
    option_expiry_date: null,
    dte: null,
    strike: null,
    right: null,
    multiplier: null,
    position: 200,
    avg_cost: 298.4,
    mark_price: 311.2,
    position_value: 62240.0,
    fifo_pnl_unrealized: 2560.0,
    fetched_at: FETCHED_AT,
  },

  // ── Short 3 calls on GLD: ATM, OTM +2%, OTM +4% (covered by the shares) ──────
  {
    id: 5,
    account_alias: ACCOUNT,
    contract_display_name: "GLD Jul'26 311 Call",
    con_id: 712880101,
    trade_groups: [GROUP_GLD_CC],
    symbol: "GLD",
    sec_type: "OPT",
    exchange: "SMART",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "GLD   260717C00311000",
    trading_class: "GLD",
    last_trade_date: "20260717",
    option_expiry_date: "20260717",
    dte: 26,
    strike: 311.0,
    right: "C",
    multiplier: "100",
    position: -1,
    avg_cost: 612.0,
    mark_price: 6.85,
    position_value: -685.0,
    fifo_pnl_unrealized: -73.0,
    fetched_at: FETCHED_AT,
  },
  {
    id: 6,
    account_alias: ACCOUNT,
    contract_display_name: "GLD Jul'26 317 Call",
    con_id: 712880145,
    trade_groups: [GROUP_GLD_CC],
    symbol: "GLD",
    sec_type: "OPT",
    exchange: "SMART",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "GLD   260717C00317000",
    trading_class: "GLD",
    last_trade_date: "20260717",
    option_expiry_date: "20260717",
    dte: 26,
    strike: 317.0,
    right: "C",
    multiplier: "100",
    position: -1,
    avg_cost: 384.0,
    mark_price: 3.4,
    position_value: -340.0,
    fifo_pnl_unrealized: 44.0,
    fetched_at: FETCHED_AT,
  },
  {
    id: 7,
    account_alias: ACCOUNT,
    contract_display_name: "GLD Jul'26 324 Call",
    con_id: 712880178,
    trade_groups: [GROUP_GLD_CC],
    symbol: "GLD",
    sec_type: "OPT",
    exchange: "SMART",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "GLD   260717C00324000",
    trading_class: "GLD",
    last_trade_date: "20260717",
    option_expiry_date: "20260717",
    dte: 26,
    strike: 324.0,
    right: "C",
    multiplier: "100",
    position: -1,
    avg_cost: 196.0,
    mark_price: 1.55,
    position_value: -155.0,
    fifo_pnl_unrealized: 41.0,
    fetched_at: FETCHED_AT,
  },
];
