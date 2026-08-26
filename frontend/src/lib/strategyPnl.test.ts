// Pure logic behind the Strategy P&L table (U4).
import { describe, expect, test } from "bun:test";

import {
  DEFAULT_SORT,
  EMPTY_CELL,
  NO_SORT,
  NO_STRATEGY_LABEL,
  buildTradeGroupsQuery,
  formatFreshness,
  formatInstruments,
  nextSortState,
  resolvePnl,
  sortRows,
  strategyLabel,
} from "./strategyPnl";
import type { TradeGroupPnlRow } from "./tradeGroups";

function row(overrides: Partial<TradeGroupPnlRow> = {}): TradeGroupPnlRow {
  return {
    id: 1,
    account_id: 1,
    name: "CL campaign",
    status: "open",
    primary_strategy_value: "core-book",
    total_pnl: 100,
    realized_pnl: 40,
    unrealized_pnl: 60,
    intraday_unrealized_pnl: null,
    intraday_realized_pnl: null,
    intraday_total_pnl: null,
    marks_as_of: null,
    live_is_stale: false,
    instruments: ["CL"],
    ...overrides,
  };
}

describe("nextSortState", () => {
  test("cycles a column desc -> asc -> unsorted across three clicks", () => {
    const first = nextSortState(NO_SORT, "total");
    expect(first).toEqual({ column: "total", direction: "desc" });

    const second = nextSortState(first, "total");
    expect(second).toEqual({ column: "total", direction: "asc" });

    const third = nextSortState(second, "total");
    expect(third).toEqual(NO_SORT);
  });

  test("switching columns starts the new one descending", () => {
    const state = nextSortState(NO_SORT, "realized");
    expect(nextSortState(state, "unrealized")).toEqual({
      column: "unrealized",
      direction: "desc",
    });
  });

  test("a name column starts ascending, then flips, then clears", () => {
    const first = nextSortState(NO_SORT, "strategy");
    expect(first).toEqual({ column: "strategy", direction: "asc" });
    const second = nextSortState(first, "strategy");
    expect(second).toEqual({ column: "strategy", direction: "desc" });
    expect(nextSortState(second, "strategy")).toEqual(NO_SORT);
  });

  test("clicking the default column advances it rather than clearing it", () => {
    expect(nextSortState(DEFAULT_SORT, "strategy")).toEqual({
      column: "strategy",
      direction: "desc",
    });
  });
});

describe("DEFAULT_SORT", () => {
  const book = [
    row({ id: 1, primary_strategy_value: "Index NQ", name: "Alpha" }),
    row({ id: 2, primary_strategy_value: "Crude Vol", name: "Zulu" }),
    row({ id: 3, primary_strategy_value: "Index NQ", name: "Zebra" }),
    row({ id: 4, primary_strategy_value: null, name: "Untagged" }),
  ];

  test("lands on strategy ascending", () => {
    expect(DEFAULT_SORT).toEqual({ column: "strategy", direction: "asc" });
  });

  test("orders strategy a-z, then group name a-z within it", () => {
    // Crude Vol < Index NQ; within Index NQ, Alpha < Zebra; untagged last.
    expect(sortRows(book, DEFAULT_SORT).map((r) => r.id)).toEqual([2, 1, 3, 4]);
  });
});

describe("sortRows on text columns", () => {
  const book = [
    row({ id: 1, primary_strategy_value: "Index NQ", name: "Alpha" }),
    row({ id: 2, primary_strategy_value: "Crude Vol", name: "Zulu" }),
    row({ id: 3, primary_strategy_value: null, name: "Untagged" }),
  ];

  test("sorts the strategy column a-z when ascending", () => {
    expect(
      sortRows(book, { column: "strategy", direction: "asc" }).map((r) => r.id),
    ).toEqual([2, 1, 3]);
  });

  test("sorts the group column a-z and z-a", () => {
    expect(
      sortRows(book, { column: "group", direction: "asc" }).map((r) => r.name),
    ).toEqual(["Alpha", "Untagged", "Zulu"]);
    expect(
      sortRows(book, { column: "group", direction: "desc" }).map((r) => r.name),
    ).toEqual(["Zulu", "Untagged", "Alpha"]);
  });

  test("keeps untagged groups at the bottom in both directions", () => {
    expect(
      sortRows(book, { column: "strategy", direction: "asc" }).at(-1)?.id,
    ).toBe(3);
    expect(
      sortRows(book, { column: "strategy", direction: "desc" }).at(-1)?.id,
    ).toBe(3);
  });

  test("compares strategy names case-insensitively", () => {
    const mixedCase = [
      row({ id: 1, primary_strategy_value: "beta", name: "b" }),
      row({ id: 2, primary_strategy_value: "Alpha", name: "a" }),
    ];
    expect(
      sortRows(mixedCase, { column: "strategy", direction: "asc" }).map(
        (r) => r.id,
      ),
    ).toEqual([2, 1]);
  });
});

describe("sortRows", () => {
  const rows = [
    row({ id: 1, total_pnl: -500 }),
    row({ id: 2, total_pnl: 1200 }),
    row({ id: 3, total_pnl: 0 }),
  ];

  test("orders a numeric P&L column descending then ascending", () => {
    expect(
      sortRows(rows, { column: "total", direction: "desc" }).map((r) => r.id),
    ).toEqual([2, 3, 1]);
    expect(
      sortRows(rows, { column: "total", direction: "asc" }).map((r) => r.id),
    ).toEqual([1, 3, 2]);
  });

  test("leaves the order untouched when unsorted", () => {
    expect(sortRows(rows, NO_SORT).map((r) => r.id)).toEqual([1, 2, 3]);
  });

  test("places rows with a null P&L last in both directions, not as zero", () => {
    const withNull = [
      row({ id: 1, total_pnl: -500 }),
      row({ id: 2, total_pnl: null, realized_pnl: null, unrealized_pnl: null }),
      row({ id: 3, total_pnl: 1200 }),
    ];
    expect(
      sortRows(withNull, { column: "total", direction: "desc" }).map(
        (r) => r.id,
      ),
    ).toEqual([3, 1, 2]);
    expect(
      sortRows(withNull, { column: "total", direction: "asc" }).map(
        (r) => r.id,
      ),
    ).toEqual([1, 3, 2]);
  });

  test("does not mutate the input array", () => {
    const original = [...rows];
    sortRows(rows, { column: "total", direction: "desc" });
    expect(rows).toEqual(original);
  });

  test("sorts on the intraday figure when the row carries one", () => {
    const mixed = [
      row({
        id: 1,
        total_pnl: 5000,
        intraday_total_pnl: 10,
        intraday_realized_pnl: 10,
      }),
      row({ id: 2, total_pnl: 100 }),
    ];
    // Row 1's settled total is larger, but its live total is what the cell shows.
    expect(
      sortRows(mixed, { column: "total", direction: "desc" }).map((r) => r.id),
    ).toEqual([2, 1]);
  });
});

describe("resolvePnl", () => {
  test("uses the settled figures when no intraday data is present", () => {
    expect(resolvePnl(row())).toEqual({
      total: 100,
      realized: 40,
      unrealized: 60,
      live: false,
    });
  });

  test("takes all three figures from the intraday layer once any is present", () => {
    const resolved = resolvePnl(
      row({
        intraday_total_pnl: 210,
        intraday_realized_pnl: 40,
        intraday_unrealized_pnl: 170,
      }),
    );
    expect(resolved).toEqual({
      total: 210,
      realized: 40,
      unrealized: 170,
      live: true,
    });
    // Total reconciles to Realized + Unrealized within the layer.
    expect(resolved.total).toBe(
      (resolved.realized ?? 0) + (resolved.unrealized ?? 0),
    );
  });
});

describe("buildTradeGroupsQuery", () => {
  test("always opts into the intraday overlay", () => {
    const query = buildTradeGroupsQuery({
      status: "open",
      accountId: "all",
      instrument: "",
    });
    expect(query).toContain("include_intraday=true");
  });

  test("omits absent filters entirely rather than sending them blank", () => {
    const query = buildTradeGroupsQuery({
      status: "all",
      accountId: "all",
      instrument: "   ",
    });
    expect(query).toBe("include_intraday=true");
  });

  test("includes each filter that is set", () => {
    const params = new URLSearchParams(
      buildTradeGroupsQuery({
        status: "open",
        accountId: "3",
        instrument: "CL.*",
      }),
    );
    expect(params.get("status")).toBe("open");
    expect(params.get("account_id")).toBe("3");
    expect(params.get("instrument")).toBe("CL.*");
  });

  test("trims the instrument pattern", () => {
    const params = new URLSearchParams(
      buildTradeGroupsQuery({
        status: "all",
        accountId: "all",
        instrument: "  CL|NG  ",
      }),
    );
    expect(params.get("instrument")).toBe("CL|NG");
  });
});

describe("formatFreshness", () => {
  test("labels a fresh mark as live", () => {
    const freshness = formatFreshness("2026-06-21T14:29:55Z", false);
    expect(freshness.tone).toBe("live");
    expect(freshness.label).toStartWith("live ");
  });

  test("labels a stale mark as stale", () => {
    const freshness = formatFreshness("2026-06-21T14:29:55Z", true);
    expect(freshness.tone).toBe("stale");
    expect(freshness.label).toStartWith("stale ");
  });

  test("says settled when there is no live mark at all", () => {
    const freshness = formatFreshness(null, false);
    expect(freshness.tone).toBe("none");
    expect(freshness.label).toBe("settled");
  });

  test("degrades to a bare label when the timestamp is unparseable", () => {
    expect(formatFreshness("not-a-date", false).label).toBe("live");
  });
});

describe("formatInstruments", () => {
  test("renders a single symbol plain", () => {
    expect(formatInstruments(["CL"])).toBe("CL");
  });

  test("comma-joins several symbols", () => {
    expect(formatInstruments(["CL", "NG"])).toBe("CL, NG");
  });

  test("renders an empty or absent set as the placeholder, not a blank cell", () => {
    expect(formatInstruments([])).toBe(EMPTY_CELL);
    expect(formatInstruments(null)).toBe(EMPTY_CELL);
  });
});

describe("strategyLabel", () => {
  test("uses the primary strategy value", () => {
    expect(strategyLabel(row())).toBe("core-book");
  });

  test("falls back to the no-strategy wording", () => {
    expect(strategyLabel(row({ primary_strategy_value: null }))).toBe(
      NO_STRATEGY_LABEL,
    );
  });
});
