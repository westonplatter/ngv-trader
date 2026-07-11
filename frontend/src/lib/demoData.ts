// Static demo fixtures used to render the UI without a live backend.
//
// Served by the demo API interceptor (see ./demoApi) when demo mode is on
// (see ./demoMode). This lets us showcase the UI — and capture screenshots —
// with a representative book of positions and the trade groups they roll up to:
//   - long 3 NQ futures contracts          → "NQ Momentum"
//   - long ES future-option call diagonal  → "ES Call Diagonal"
//   - long 200 GLD shares + short 3 calls  → "GLD Covered Calls"
//     (calls at ATM, OTM +2%, OTM +4%)
//   - long 3 MES futures (intraday)        → "MES Intraday Scalp"   (all live)
//   - long 5 SPY puts (intraday)           → "SPY Protective Puts"  (all live)
//
// The book also carries unsettled (live TWS) trades so the settled-vs-live
// distinction is visible in the UI:
//   - existing settled groups (NQ Momentum, GLD Covered Calls) each pick up an
//     intraday fill that has not yet settled — rendered with an "unsettled"
//     badge in the Trades table alongside the settled openings;
//   - the two new intraday groups are entirely live: their positions show
//     source="live" and their opening fills are all unsettled.
// Unsettled executions carry settled=false and data_source="tws"; settled
// openings carry data_source="demo" and no settled flag.
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
// Timestamp stamped on intraday marks and unsettled fills. Groups that carry
// any live data report this as their marks_as_of so the detail header shows
// "live as of …" instead of the settled snapshot date.
const LIVE_MARK_TS = "2026-06-21T14:29:55Z";

// Trade groups the demo positions roll up to. Names render as links in the
// Positions table's "Trade Group" column and as the list on the Tagging page.
const GROUP_NQ: TradeGroupRef = { id: 101, name: "NQ Momentum" };
const GROUP_ES_DIAGONAL: TradeGroupRef = { id: 102, name: "ES Call Diagonal" };
const GROUP_GLD_CC: TradeGroupRef = { id: 103, name: "GLD Covered Calls" };
// Two groups opened intraday — entirely live/unsettled until they settle T+1.
const GROUP_MES_SCALP: TradeGroupRef = { id: 104, name: "MES Intraday Scalp" };
const GROUP_SPY_PUTS: TradeGroupRef = { id: 105, name: "SPY Protective Puts" };

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
    account_id: ACCOUNT_ID,
    source: "settled",
    mark: null,
    mark_ts: null,
    live_unrealized: null,
    iv: null,
    delta: null,
    gamma: null,
    theta: null,
    vega: null,
    und_price: null,
    intrinsic_value: null,
    extrinsic_value: null,
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
    account_id: ACCOUNT_ID,
    source: "live",
    mark: 95.0,
    mark_ts: "2026-06-21T14:29:50Z",
    live_unrealized: 1250.0,
    iv: 0.145,
    delta: 0.55,
    gamma: 0.0008,
    theta: -1.85,
    vega: 4.2,
    und_price: 6055.0,
    intrinsic_value: 55.0,
    extrinsic_value: 40.0,
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
    account_id: ACCOUNT_ID,
    source: "live",
    mark: 172.0,
    mark_ts: "2026-06-21T14:29:50Z",
    live_unrealized: 1500.0,
    iv: 0.152,
    delta: 0.47,
    gamma: 0.0007,
    theta: -1.4,
    vega: 6.1,
    und_price: 6055.0,
    intrinsic_value: 0.0,
    extrinsic_value: 172.0,
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
    account_id: ACCOUNT_ID,
    source: "settled",
    mark: null,
    mark_ts: null,
    live_unrealized: null,
    iv: null,
    delta: null,
    gamma: null,
    theta: null,
    vega: null,
    und_price: null,
    intrinsic_value: null,
    extrinsic_value: null,
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
    account_id: ACCOUNT_ID,
    source: "live",
    mark: 6.9,
    mark_ts: "2026-06-21T14:29:52Z",
    live_unrealized: -78.0,
    iv: 0.182,
    delta: 0.71,
    gamma: 0.04,
    theta: -0.11,
    vega: 0.22,
    und_price: 316.2,
    intrinsic_value: 5.2,
    extrinsic_value: 1.7,
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
    account_id: ACCOUNT_ID,
    source: "live",
    mark: 3.3,
    mark_ts: "2026-06-21T14:29:52Z",
    live_unrealized: 54.0,
    iv: 0.176,
    delta: 0.46,
    gamma: 0.05,
    theta: -0.1,
    vega: 0.2,
    und_price: 316.2,
    intrinsic_value: 0.0,
    extrinsic_value: 3.3,
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
    account_id: ACCOUNT_ID,
    source: "live",
    mark: 1.45,
    mark_ts: "2026-06-21T14:29:52Z",
    live_unrealized: 51.0,
    iv: 0.171,
    delta: 0.23,
    gamma: 0.03,
    theta: -0.08,
    vega: 0.14,
    und_price: 316.2,
    intrinsic_value: 0.0,
    extrinsic_value: 1.45,
  },
  // ── Live TWS position opened intraday, not yet assigned to a trade group ─────
  // Demonstrates the inline "Trade Group" picker on the Positions page: a
  // real-time fill from TWS shows source="live" with no group until assigned.
  {
    id: 8,
    account_id: ACCOUNT_ID,
    account_alias: ACCOUNT_ALIAS,
    contract_display_name: "CL Sep'26 Future",
    con_id: 689918823,
    trade_groups: [],
    symbol: "CL",
    sec_type: "FUT",
    exchange: "NYMEX",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "CLU6",
    trading_class: "CL",
    last_trade_date: "20260820",
    option_expiry_date: null,
    dte: 57,
    strike: null,
    right: null,
    multiplier: "1000",
    position: 2,
    avg_cost: 71.4,
    mark_price: null,
    position_value: null,
    fifo_pnl_unrealized: null,
    fetched_at: FETCHED_AT,
    source: "live",
    mark: 72.18,
    mark_ts: LIVE_MARK_TS,
    live_unrealized: 1560.0,
    iv: null,
    delta: null,
    gamma: null,
    theta: null,
    vega: null,
    und_price: null,
    intrinsic_value: null,
    extrinsic_value: null,
  },

  // ── Long 3 MES futures opened intraday → "MES Intraday Scalp" ────────────────
  // A brand-new group whose only leg is a live TWS position: no settled snapshot
  // yet (mark_price/position_value/fifo_pnl_unrealized are null), just the live
  // overlay. avg_cost is the blended price of the two unsettled opening fills.
  {
    id: 9,
    account_id: ACCOUNT_ID,
    account_alias: ACCOUNT_ALIAS,
    contract_display_name: "MES Sep'26 Future",
    con_id: 730341577,
    trade_groups: [GROUP_MES_SCALP],
    symbol: "MES",
    sec_type: "FUT",
    exchange: "CME",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "MESU6",
    trading_class: "MES",
    last_trade_date: "20260918",
    option_expiry_date: null,
    dte: 89,
    strike: null,
    right: null,
    multiplier: "5",
    position: 3,
    avg_cost: 5510.5,
    mark_price: null,
    position_value: null,
    fifo_pnl_unrealized: null,
    fetched_at: FETCHED_AT,
    source: "live",
    mark: 5514.75,
    mark_ts: LIVE_MARK_TS,
    live_unrealized: 63.75,
  },

  // ── Long 5 SPY puts opened intraday → "SPY Protective Puts" ──────────────────
  // Options analogue of the MES scalp: a live-only hedge just put on. avg_cost is
  // multiplier-inclusive (premium * 100); mark is the per-contract premium.
  {
    id: 10,
    account_id: ACCOUNT_ID,
    account_alias: ACCOUNT_ALIAS,
    contract_display_name: "SPY Jul'26 540 Put",
    con_id: 712994310,
    trade_groups: [GROUP_SPY_PUTS],
    symbol: "SPY",
    sec_type: "OPT",
    exchange: "SMART",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "SPY   260717P00540000",
    trading_class: "SPY",
    last_trade_date: "20260717",
    option_expiry_date: "20260717",
    dte: 26,
    strike: 540.0,
    right: "P",
    multiplier: "100",
    position: 5,
    avg_cost: 385.0,
    mark_price: null,
    position_value: null,
    fifo_pnl_unrealized: null,
    fetched_at: FETCHED_AT,
    source: "live",
    mark: 4.1,
    mark_ts: LIVE_MARK_TS,
    live_unrealized: 125.0,
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
  {
    id: GROUP_MES_SCALP.id,
    account_id: ACCOUNT_ID,
    name: GROUP_MES_SCALP.name,
    notes: "Long MES scalp opened intraday — live fills, not yet settled.",
    status: "open",
    primary_strategy_value: DEMO_STRATEGIES[0].value,
    opened_at: "2026-06-21T14:22:10Z",
    closed_at: null,
    opened_by: "demo",
    closed_by: null,
  },
  {
    id: GROUP_SPY_PUTS.id,
    account_id: ACCOUNT_ID,
    name: GROUP_SPY_PUTS.name,
    notes: "Long SPY puts as an intraday hedge — live fill, not yet settled.",
    status: "open",
    primary_strategy_value: DEMO_STRATEGIES[0].value,
    opened_at: "2026-06-21T14:27:15Z",
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
  [GROUP_MES_SCALP.id]: [9],
  [GROUP_SPY_PUTS.id]: [10],
};

// Unsettled (live TWS) fills per group. These render in the Trades table with an
// "unsettled" badge (GroupExecution.settled === false) and carry
// data_source="tws". Existing settled groups pick up an intraday fill; the two
// intraday groups are made up entirely of unsettled openings — one per fill that
// composes the live position above (quantities sum to the position). Prices
// follow the execution convention: per-unit for futures, multiplier-inclusive
// premium for options (mirroring how openingExecution reuses avg_cost).
const GROUP_UNSETTLED_EXECUTIONS: Record<number, GroupExecution[]> = {
  // NQ Momentum: scaled in one more contract intraday.
  [GROUP_NQ.id]: [
    {
      id: 5101,
      trade_id: null,
      account_id: ACCOUNT_ID,
      account_alias: ACCOUNT_ALIAS,
      executed_at: "2026-06-21T14:12:30Z",
      side: "BOT",
      quantity: 1,
      price: 22005.0,
      commission: 2.25,
      realized_pnl: 0,
      exec_role: "standalone",
      sec_type: "FUT",
      contract_display: "NQ Sep'26 Future",
      data_source: "tws",
      settled: false,
    },
  ],
  // GLD Covered Calls: sold one more further-OTM call intraday (+6%).
  [GROUP_GLD_CC.id]: [
    {
      id: 5103,
      trade_id: null,
      account_id: ACCOUNT_ID,
      account_alias: ACCOUNT_ALIAS,
      executed_at: "2026-06-21T14:18:05Z",
      side: "SLD",
      quantity: 1,
      price: 95.0,
      commission: 1.05,
      realized_pnl: 0,
      exec_role: "standalone",
      sec_type: "OPT",
      contract_display: "GLD Jul'26 330 Call",
      data_source: "tws",
      settled: false,
    },
  ],
  // MES Intraday Scalp: two opening fills that build the live 3-lot position.
  [GROUP_MES_SCALP.id]: [
    {
      id: 5104,
      trade_id: null,
      account_id: ACCOUNT_ID,
      account_alias: ACCOUNT_ALIAS,
      executed_at: "2026-06-21T14:22:10Z",
      side: "BOT",
      quantity: 2,
      price: 5510.25,
      commission: 0.62,
      realized_pnl: 0,
      exec_role: "standalone",
      sec_type: "FUT",
      contract_display: "MES Sep'26 Future",
      data_source: "tws",
      settled: false,
    },
    {
      id: 5105,
      trade_id: null,
      account_id: ACCOUNT_ID,
      account_alias: ACCOUNT_ALIAS,
      executed_at: "2026-06-21T14:25:40Z",
      side: "BOT",
      quantity: 1,
      price: 5511.0,
      commission: 0.31,
      realized_pnl: 0,
      exec_role: "standalone",
      sec_type: "FUT",
      contract_display: "MES Sep'26 Future",
      data_source: "tws",
      settled: false,
    },
  ],
  // SPY Protective Puts: single opening fill for the live 5-lot hedge.
  [GROUP_SPY_PUTS.id]: [
    {
      id: 5106,
      trade_id: null,
      account_id: ACCOUNT_ID,
      account_alias: ACCOUNT_ALIAS,
      executed_at: "2026-06-21T14:27:15Z",
      side: "BOT",
      quantity: 5,
      price: 385.0,
      commission: 3.25,
      realized_pnl: 0,
      exec_role: "standalone",
      sec_type: "OPT",
      contract_display: "SPY Jul'26 540 Put",
      data_source: "tws",
      settled: false,
    },
  ],
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
    source: pos.source,
    mark: pos.mark,
    mark_ts: pos.mark_ts,
    live_unrealized: pos.live_unrealized,
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

// Executions the group exposes: one synthetic opening per settled position plus
// any unsettled live fills. Live positions are excluded here — their fills come
// from the unsettled list, not a synthetic settled opening — so quantities and
// the execution count don't double-count them.
function groupExecutions(groupId: number): GroupExecution[] {
  const settledOpenings = (GROUP_POSITION_IDS[groupId] ?? [])
    .map((id) => POSITIONS_BY_ID.get(id))
    .filter((p): p is Position => p != null && p.source !== "live")
    .map((p, i) => openingExecution(p, i));
  return [...settledOpenings, ...(GROUP_UNSETTLED_EXECUTIONS[groupId] ?? [])];
}

export function demoTradeGroupDetail(groupId: number): TradeGroupDetail | null {
  const group = DEMO_TRADE_GROUPS.find((g) => g.id === groupId);
  if (!group) return null;
  return {
    ...group,
    execution_count: groupExecutions(groupId).length,
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
  // Settled unrealized comes from the T-1 snapshot; live positions carry none
  // (fifo_pnl_unrealized is null) and instead contribute their live_unrealized
  // to the additive intraday overlay.
  const settledUnrealized = positions.reduce(
    (sum, p) => sum + (p.fifo_pnl_unrealized ?? 0),
    0,
  );
  const liveUnrealized = positions.reduce(
    (sum, p) => sum + (p.live_unrealized ?? 0),
    0,
  );
  const executions = groupExecutions(groupId);
  const hasLive =
    liveUnrealized !== 0 ||
    positions.some((p) => p.source === "live") ||
    executions.some((e) => e.settled === false);
  return {
    trade_group_id: groupId,
    total_realized_pnl: 0,
    total_unrealized_pnl: settledUnrealized,
    executions,
    open_positions: positions.map(toOpenPosition),
    intraday_unrealized_pnl: settledUnrealized + liveUnrealized,
    intraday_realized_pnl: 0,
    intraday_total_pnl: settledUnrealized + liveUnrealized,
    // Groups with any live data report a live timestamp so the detail header
    // shows "live as of …"; settled-only groups keep the snapshot date.
    marks_as_of: hasLive ? LIVE_MARK_TS : AS_OF,
    by_account: [],
  };
}
