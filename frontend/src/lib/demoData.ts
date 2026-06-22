// Static demo fixtures used to render the UI without a live backend.
//
// Served by the demo API interceptor (see ./demoApi) when demo mode is on
// (see ./demoMode). This lets us showcase the UI — and capture screenshots —
// with a representative book of positions and the trade groups they roll up to:
//   - long 3 NQ futures contracts          → "NQ Momentum"
//   - long ES future-option call diagonal  → "ES Call Diagonal"
//   - long 200 GLD shares + short 3 calls  → "GLD Covered Calls"
//     (calls at ATM, OTM +2%, OTM +4%)
//
// Fixtures reuse the real component/API types so they cannot silently drift
// from the shapes the UI actually consumes.

import type { Position, TradeGroupRef } from "../components/PositionsTable";
import type {
  GroupExecution,
  GroupExecutionsResponse,
  GroupOpenPosition,
  Tag,
  TradeGroup,
  TradeGroupDetail,
} from "../components/TradeTaggingPage";

const ACCOUNT_ALIAS = "DU1234567";
const ACCOUNT_ID = 1;
const FETCHED_AT = "2026-06-21T14:30:00Z";
const AS_OF = "2026-06-21";

// Trade groups the demo positions roll up to. Names render as links in the
// Positions table's "Trade Group" column and as the list on the Tagging page.
const GROUP_NQ: TradeGroupRef = { id: 101, name: "NQ Momentum" };
const GROUP_ES_DIAGONAL: TradeGroupRef = { id: 102, name: "ES Call Diagonal" };
const GROUP_GLD_CC: TradeGroupRef = { id: 103, name: "GLD Covered Calls" };

export const DEMO_POSITIONS: Position[] = [
  // ── Long 3 NQ futures contracts ────────────────────────────────────────────
  {
    id: 1,
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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
    account_alias: ACCOUNT_ALIAS,
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

// ── Tagging workspace ─────────────────────────────────────────────────────────

// A single umbrella strategy keeps the demo coherent and ensures Trade Group
// links from the Positions page always resolve to a populated group.
export const DEMO_STRATEGIES: Tag[] = [
  {
    id: 1,
    tag_type: "strategy",
    value: "core-book",
    normalized_value: "core-book",
    created_by: "demo",
    created_at: "2026-05-01T00:00:00Z",
    archived_at: null,
  },
];

export const DEMO_TRADE_GROUPS: TradeGroup[] = [
  {
    id: GROUP_NQ.id,
    account_id: ACCOUNT_ID,
    name: GROUP_NQ.name,
    notes: "Long NQ futures — trend continuation.",
    status: "open",
    primary_strategy_value: DEMO_STRATEGIES[0].value,
    opened_at: "2026-06-05T15:02:00Z",
    closed_at: null,
    opened_by: "demo",
    closed_by: null,
  },
  {
    id: GROUP_ES_DIAGONAL.id,
    account_id: ACCOUNT_ID,
    name: GROUP_ES_DIAGONAL.name,
    notes: "Long call diagonal: short-dated 6000C vs longer-dated 6100C.",
    status: "open",
    primary_strategy_value: DEMO_STRATEGIES[0].value,
    opened_at: "2026-06-10T18:20:00Z",
    closed_at: null,
    opened_by: "demo",
    closed_by: null,
  },
  {
    id: GROUP_GLD_CC.id,
    account_id: ACCOUNT_ID,
    name: GROUP_GLD_CC.name,
    notes: "200 GLD shares overwritten with calls at ATM / +2% / +4%.",
    status: "open",
    primary_strategy_value: DEMO_STRATEGIES[0].value,
    opened_at: "2026-06-12T14:31:00Z",
    closed_at: null,
    opened_by: "demo",
    closed_by: null,
  },
];

// Map each group to the position rows that belong to it (by position id).
const GROUP_POSITION_IDS: Record<number, number[]> = {
  [GROUP_NQ.id]: [1],
  [GROUP_ES_DIAGONAL.id]: [2, 3],
  [GROUP_GLD_CC.id]: [4, 5, 6, 7],
};

function toOpenPosition(pos: Position): GroupOpenPosition {
  return {
    account_id: ACCOUNT_ID,
    account_alias: pos.account_alias,
    con_id: pos.con_id,
    symbol: pos.symbol,
    local_symbol: pos.local_symbol,
    contract_display: pos.contract_display_name,
    sec_type: pos.sec_type,
    position: pos.position,
    avg_cost: pos.avg_cost,
    multiplier: pos.multiplier,
    mark_price: pos.mark_price,
    position_value: pos.position_value,
    fifo_pnl_unrealized: pos.fifo_pnl_unrealized,
    as_of_date: AS_OF,
  };
}

// One opening execution per leg, derived from the demo positions so the
// quantities line up with the open positions shown alongside them.
function openingExecution(pos: Position, index: number): GroupExecution {
  const isShort = pos.position < 0;
  return {
    id: 1000 + pos.id,
    trade_id: 2000 + pos.id,
    account_id: ACCOUNT_ID,
    account_alias: pos.account_alias,
    executed_at: `2026-06-1${index}T15:30:00Z`,
    side: isShort ? "SLD" : "BOT",
    quantity: Math.abs(pos.position),
    price: pos.avg_cost,
    commission: pos.sec_type === "STK" ? 1.0 : 2.25,
    realized_pnl: 0,
    exec_role: "opening",
    sec_type: pos.sec_type,
    contract_display: pos.contract_display_name,
    data_source: "demo",
  };
}

const POSITIONS_BY_ID = new Map(DEMO_POSITIONS.map((p) => [p.id, p]));

export function demoTradeGroupDetail(groupId: number): TradeGroupDetail | null {
  const group = DEMO_TRADE_GROUPS.find((g) => g.id === groupId);
  if (!group) return null;
  const positionIds = GROUP_POSITION_IDS[groupId] ?? [];
  return {
    ...group,
    execution_count: positionIds.length,
    tags: [
      {
        id: groupId,
        entity_type: "trade_group",
        entity_id: groupId,
        tag_id: DEMO_STRATEGIES[0].id,
        tag_type: "strategy",
        is_primary: true,
        source: "demo",
        created_by: "demo",
      },
    ],
  };
}

export function demoGroupExecutions(
  groupId: number,
): GroupExecutionsResponse | null {
  if (!DEMO_TRADE_GROUPS.some((g) => g.id === groupId)) return null;
  const positions = (GROUP_POSITION_IDS[groupId] ?? [])
    .map((id) => POSITIONS_BY_ID.get(id))
    .filter((p): p is Position => p != null);
  const totalUnrealized = positions.reduce(
    (sum, p) => sum + (p.fifo_pnl_unrealized ?? 0),
    0,
  );
  return {
    trade_group_id: groupId,
    total_realized_pnl: 0,
    total_unrealized_pnl: totalUnrealized,
    executions: positions.map((p, i) => openingExecution(p, i)),
    open_positions: positions.map(toOpenPosition),
  };
}
