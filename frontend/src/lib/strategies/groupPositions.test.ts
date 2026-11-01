import { describe, expect, test } from "bun:test";
import type { GroupExecution, GroupOpenPosition } from "../../types/tradeGroups";
import {
  accountBands,
  capitalForAccount,
  groupCapital,
  hasFreshLive,
  parseMultiplier,
  positionGreeks,
  positionStrike,
  positionTotals,
  runningRealized,
  sortAccountPnl,
  sortGroupPositions,
  totalPnl,
} from "./groupPositions";

function position(overrides: Partial<GroupOpenPosition>): GroupOpenPosition {
  return {
    account_id: 1,
    account_alias: "A",
    con_id: 1,
    symbol: "CL",
    local_symbol: null,
    contract_display: "CL 70.5 CALL",
    sec_type: "FOP",
    right: "C",
    option_expiry_date: null,
    dte: null,
    strike: 70.5,
    position: -1,
    avg_cost: 1000,
    multiplier: "1000",
    mark_price: null,
    position_value: null,
    fifo_pnl_unrealized: null,
    as_of_date: null,
    source: "flex",
    mark: null,
    mark_ts: null,
    live_unrealized: null,
    live_fetched_at: null,
    live_is_stale: false,
    delta: null,
    gamma: null,
    iv: null,
    ...overrides,
  };
}

describe("parseMultiplier", () => {
  test("falls back to 1 for missing, blank, zero, or junk", () => {
    expect(parseMultiplier("1000")).toBe(1000);
    expect(parseMultiplier(null)).toBe(1);
    expect(parseMultiplier("")).toBe(1);
    expect(parseMultiplier("0")).toBe(1);
    expect(parseMultiplier("x")).toBe(1);
  });
});

describe("positionGreeks", () => {
  test("options scale per-unit greeks by signed qty and multiplier", () => {
    const g = positionGreeks(position({ delta: 0.5, gamma: 0.01, position: -2 }));
    expect(g.delta).toBe(-1000);
    expect(g.gamma).toBe(-20);
  });

  test("a stale live overlay blanks option greeks", () => {
    expect(positionGreeks(position({ delta: 0.5, live_is_stale: true }))).toEqual(
      { delta: null, gamma: null },
    );
  });

  test("futures and stock are delta one per unit, gamma zero, even when stale", () => {
    expect(
      positionGreeks(
        position({ sec_type: "FUT", position: 3, multiplier: "100", live_is_stale: true }),
      ),
    ).toEqual({ delta: 300, gamma: 0 });
    expect(
      positionGreeks(position({ sec_type: "STK", position: 200, multiplier: null })),
    ).toEqual({ delta: 200, gamma: 0 });
  });
});

describe("sortGroupPositions", () => {
  test("account, then symbol, then strike high to low, then natural display", () => {
    const rows = [
      position({ con_id: 1, account_alias: "B", symbol: "CL", contract_display: "CL 70 CALL" }),
      position({ con_id: 2, account_alias: "A", symbol: "ES", contract_display: "ES 6000 PUT" }),
      position({ con_id: 3, account_alias: "A", symbol: "CL", contract_display: "CL 70 CALL" }),
      position({ con_id: 4, account_alias: "A", symbol: "CL", contract_display: "CL 75 CALL" }),
      position({ con_id: 5, account_alias: "A", symbol: "CL", contract_display: "CLZ10", sec_type: "FUT" }),
      position({ con_id: 6, account_alias: "A", symbol: "CL", contract_display: "CLZ9", sec_type: "FUT" }),
    ];
    expect(sortGroupPositions(rows).map((r) => r.con_id)).toEqual([4, 3, 6, 5, 2, 1]);
    expect(positionStrike(rows[0])).toBe(70);
    expect(positionStrike(rows[4])).toBeNull();
  });
});

describe("accountBands", () => {
  test("alternates 0/1 per account in first-seen order", () => {
    const bands = accountBands([
      position({ account_id: 3 }),
      position({ account_id: 1 }),
      position({ account_id: 3 }),
      position({ account_id: 2 }),
    ]);
    expect([...bands.entries()]).toEqual([
      [3, 0],
      [1, 1],
      [2, 0],
    ]);
  });
});

describe("positionTotals", () => {
  test("sums signed basis, settled fields always, live fields only when fresh", () => {
    const totals = positionTotals([
      position({
        position: -1,
        avg_cost: 1000,
        position_value: -900,
        fifo_pnl_unrealized: 100,
        delta: 0.5,
        gamma: 0.01,
        source: "live",
        live_unrealized: 120,
      }),
      position({
        position: 2,
        avg_cost: 500,
        position_value: 1100,
        fifo_pnl_unrealized: 100,
        delta: 0.4,
        source: "live",
        live_is_stale: true,
        live_unrealized: 999,
      }),
    ]);
    expect(totals.avgCost).toEqual({ sum: -500, count: 2 });
    expect(totals.costBasis).toEqual({ sum: 0, count: 2 });
    expect(totals.value).toEqual({ sum: 200, count: 2 });
    expect(totals.unrealized).toEqual({ sum: 200, count: 2 });
    expect(totals.liveUnrealized).toEqual({ sum: 120, count: 1 });
    expect(totals.delta).toEqual({ sum: -500, count: 1 });
    expect(totals.gamma).toEqual({ sum: -10, count: 1 });
  });
});

describe("capital", () => {
  const legs = [
    position({ account_id: 1, sec_type: "FOP", position: -1, avg_cost: 1200 }),
    position({ account_id: 1, sec_type: "FOP", position: 1, avg_cost: 800 }),
    position({ account_id: 2, sec_type: "STK", position: 100, avg_cost: 50 }),
  ];

  test("groupCapital nets spread legs per bucket and reports magnitudes", () => {
    expect(groupCapital(legs)).toEqual({
      capital: 5400,
      optionsCapital: 400,
      equityCapital: 5000,
    });
  });

  test("groupCapital is all null with no positions or a zero net", () => {
    expect(groupCapital([])).toEqual({ capital: null, optionsCapital: null, equityCapital: null });
    expect(
      groupCapital([
        position({ position: -1, avg_cost: 100 }),
        position({ position: 1, avg_cost: 100 }),
      ]),
    ).toEqual({ capital: null, optionsCapital: null, equityCapital: null });
  });

  test("capitalForAccount uses the same convention and is null for an absent account", () => {
    expect(capitalForAccount(legs, 1)).toBe(400);
    expect(capitalForAccount(legs, 2)).toBe(5000);
    expect(capitalForAccount(legs, 9)).toBeNull();
  });
});

describe("P&L helpers", () => {
  test("totalPnl treats a lone null as zero and both null as unknown", () => {
    expect(totalPnl(10, null)).toBe(10);
    expect(totalPnl(null, -5)).toBe(-5);
    expect(totalPnl(null, null)).toBeNull();
  });

  test("sortAccountPnl orders by total desc with unknowns last", () => {
    const sorted = sortAccountPnl([
      { account_id: 1, account_alias: null, realized_pnl: null, unrealized_pnl: null, intraday_unrealized_pnl: null, intraday_realized_pnl: null, intraday_total_pnl: null },
      { account_id: 2, account_alias: null, realized_pnl: 5, unrealized_pnl: 5, intraday_unrealized_pnl: null, intraday_realized_pnl: null, intraday_total_pnl: null },
      { account_id: 3, account_alias: null, realized_pnl: 50, unrealized_pnl: null, intraday_unrealized_pnl: null, intraday_realized_pnl: null, intraday_total_pnl: null },
    ]);
    expect(sorted.map((a) => a.account_id)).toEqual([3, 2, 1]);
  });

  test("hasFreshLive needs a live, non-stale position", () => {
    expect(hasFreshLive([position({ source: "live" })])).toBe(true);
    expect(hasFreshLive([position({ source: "live", live_is_stale: true })])).toBe(false);
    expect(hasFreshLive([position({})])).toBe(false);
  });

  test("runningRealized skips combo summaries and rows without P&L", () => {
    const ex = (overrides: Partial<GroupExecution>): GroupExecution => ({
      id: 1,
      trade_id: 1,
      account_id: 1,
      account_alias: null,
      executed_at: "2026-06-01T00:00:00Z",
      side: "BOT",
      quantity: 1,
      price: 1,
      commission: null,
      realized_pnl: null,
      exec_role: "standalone",
      sec_type: null,
      contract_display: null,
      data_source: "demo",
      ib_codes: null,
      ...overrides,
    });
    const rows = runningRealized([
      ex({ id: 1, realized_pnl: 10 }),
      ex({ id: 2, realized_pnl: 100, exec_role: "combo_summary" }),
      ex({ id: 3, realized_pnl: null }),
      ex({ id: 4, realized_pnl: -4 }),
    ]);
    expect(rows.map((r) => [r.counted, r.running])).toEqual([
      [true, 10],
      [false, 10],
      [false, 10],
      [true, 6],
    ]);
  });
});
