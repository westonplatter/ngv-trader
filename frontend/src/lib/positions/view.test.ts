import { describe, expect, test } from "bun:test";
import type { Position } from "../../types/positions";
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  accountAliases,
  expiryForPosition,
  filterPositions,
  isLiveFresh,
  nextSort,
  parseDte,
  positionCostBasis,
  positionTotals,
  regexMatch,
  sortPositions,
} from "./view";

function position(overrides: Partial<Position>): Position {
  return {
    id: 1,
    account_id: 1,
    account_alias: "DU1234567",
    contract_display_name: "ES Mar'27 6000 Call",
    con_id: 100,
    trade_groups: [],
    symbol: "ES",
    sec_type: "FOP",
    exchange: "CME",
    primary_exchange: null,
    currency: "USD",
    local_symbol: "ESH7 C6000",
    trading_class: "ES",
    last_trade_date: "20270319",
    option_expiry_date: "20270319",
    dte: 120,
    strike: 6000,
    right: "C",
    multiplier: "50",
    position: -1,
    avg_cost: 2500,
    mark_price: 40,
    position_value: -2000,
    fifo_pnl_unrealized: 500,
    fetched_at: "2026-06-21T14:30:00Z",
    source: "flex",
    mark: null,
    mark_ts: null,
    live_unrealized: null,
    live_fetched_at: null,
    live_is_stale: false,
    iv: null,
    delta: null,
    gamma: null,
    theta: null,
    vega: null,
    und_price: null,
    intrinsic_value: null,
    extrinsic_value: null,
    ...overrides,
  };
}

const ROWS: Position[] = [
  position({ id: 1, con_id: 300, symbol: "NQ", dte: 10, account_alias: "B" }),
  position({ id: 2, con_id: 100, symbol: "ES", dte: 120 }),
  position({
    id: 3,
    con_id: 200,
    symbol: "ES",
    sec_type: "FUT",
    option_expiry_date: null,
    dte: null,
    local_symbol: "ESM7",
  }),
  position({ id: 4, con_id: 400, symbol: null, dte: 5 }),
];

describe("nextSort", () => {
  test("a new column is selected without ordering, then cycles", () => {
    const first = nextSort(DEFAULT_SORT, "dte");
    expect(first).toEqual({ column: "dte", direction: "none" });
    const asc = nextSort(first, "dte");
    expect(asc).toEqual({ column: "dte", direction: "asc" });
    const desc = nextSort(asc, "dte");
    expect(desc).toEqual({ column: "dte", direction: "desc" });
    expect(nextSort(desc, "dte")).toEqual({ column: null, direction: "none" });
  });
});

describe("sortPositions", () => {
  test("returns a copy in input order when unsorted", () => {
    const out = sortPositions(ROWS, { column: null, direction: "none" });
    expect(out.map((r) => r.id)).toEqual([1, 2, 3, 4]);
    expect(out).not.toBe(ROWS);
  });

  test("sorts by symbol with nulls last and con_id as tiebreak", () => {
    const asc = sortPositions(ROWS, { column: "symbol", direction: "asc" });
    expect(asc.map((r) => r.id)).toEqual([2, 3, 1, 4]);
    const desc = sortPositions(ROWS, { column: "symbol", direction: "desc" });
    expect(desc.map((r) => r.id)).toEqual([1, 2, 3, 4]);
  });

  test("sorts by dte numerically, missing last", () => {
    const asc = sortPositions(ROWS, { column: "dte", direction: "asc" });
    expect(asc.map((r) => r.dte)).toEqual([5, 10, 120, null]);
  });

  test("sorts expiry whether dashed or compact", () => {
    const rows = [
      position({ id: 1, con_id: 1, option_expiry_date: "2027-06-18" }),
      position({ id: 2, con_id: 2, option_expiry_date: "20270319" }),
      position({ id: 3, con_id: 3, option_expiry_date: "soon" }),
    ];
    const asc = sortPositions(rows, {
      column: "option_expiry_date",
      direction: "asc",
    });
    expect(asc.map((r) => r.id)).toEqual([2, 1, 3]);
  });
});

describe("filterPositions", () => {
  test("no filters keeps everything", () => {
    expect(filterPositions(ROWS, EMPTY_FILTERS)).toHaveLength(4);
  });

  test("account filter matches the alias exactly", () => {
    const out = filterPositions(ROWS, { ...EMPTY_FILTERS, account: "B" });
    expect(out.map((r) => r.id)).toEqual([1]);
  });

  test("symbol filter is a case-insensitive regex", () => {
    expect(
      filterPositions(ROWS, { ...EMPTY_FILTERS, symbol: "^e" }).map((r) => r.id),
    ).toEqual([2, 3]);
  });

  test("an invalid regex falls back to substring", () => {
    expect(regexMatch("ESM7", "(")).toBe(false);
    expect(regexMatch("a(b", "(")).toBe(true);
    expect(
      filterPositions(ROWS, { ...EMPTY_FILTERS, localSymbol: "ESM7(" }),
    ).toHaveLength(0);
  });

  test("a DTE bound drops rows without a DTE", () => {
    const out = filterPositions(ROWS, { ...EMPTY_FILTERS, dteMin: "6" });
    expect(out.map((r) => r.id)).toEqual([1, 2]);
    const both = filterPositions(ROWS, {
      ...EMPTY_FILTERS,
      dteMin: "6",
      dteMax: "20",
    });
    expect(both.map((r) => r.id)).toEqual([1]);
  });

  test("a non-numeric DTE bound is ignored", () => {
    expect(parseDte("abc")).toBeNull();
    expect(parseDte(" ")).toBeNull();
    expect(parseDte("12")).toBe(12);
    expect(filterPositions(ROWS, { ...EMPTY_FILTERS, dteMin: "x" })).toHaveLength(
      4,
    );
  });
});

describe("row helpers", () => {
  test("accountAliases is sorted and unique", () => {
    expect(accountAliases(ROWS)).toEqual(["B", "DU1234567"]);
  });

  test("expiryForPosition prefers the option expiry for options and the last trade date for futures", () => {
    expect(expiryForPosition(ROWS[1])).toBe("2027-03-19");
    expect(
      expiryForPosition(
        position({ sec_type: "FUT", last_trade_date: "20270618" }),
      ),
    ).toBe("2027-06-18");
  });

  test("positionCostBasis is value minus unrealized, or null", () => {
    expect(positionCostBasis(ROWS[1])).toBe(-2500);
    expect(positionCostBasis(position({ position_value: null }))).toBeNull();
  });

  test("isLiveFresh needs a live source that is not stale", () => {
    expect(isLiveFresh(position({ source: "live" }))).toBe(true);
    expect(isLiveFresh(position({ source: "live", live_is_stale: true }))).toBe(
      false,
    );
    expect(isLiveFresh(position({ source: "flex" }))).toBe(false);
  });
});

describe("positionTotals", () => {
  test("sums settled and live figures, using live only when fresh", () => {
    const rows = [
      position({
        fifo_pnl_unrealized: 100,
        position_value: 1000,
        source: "live",
        live_unrealized: 150,
        mark_ts: "2026-06-21T14:30:00Z",
      }),
      position({
        fifo_pnl_unrealized: -40,
        position_value: 500,
        source: "live",
        live_is_stale: true,
        live_unrealized: 999,
        mark_ts: "2026-06-22T09:00:00Z",
      }),
      position({ fifo_pnl_unrealized: null, position_value: null }),
    ];
    const totals = positionTotals(rows);
    expect(totals.unrealized).toBe(60);
    expect(totals.liveUnrealized).toBe(110);
    expect(totals.costBasis).toBe(1440);
    expect(totals.newestMarkTs).toBe("2026-06-21T14:30:00Z");
  });

  test("is all nulls for rows without figures", () => {
    const totals = positionTotals([
      position({ fifo_pnl_unrealized: null, position_value: null }),
    ]);
    expect(totals).toEqual({
      unrealized: null,
      liveUnrealized: null,
      costBasis: null,
      newestMarkTs: null,
    });
  });
});
