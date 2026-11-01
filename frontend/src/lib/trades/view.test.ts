import { describe, expect, test } from "bun:test";
import type { TradeExecutionRow } from "../../types/trades";
import {
  accountOptions,
  compileSymbolRegex,
  filterExecutions,
  formatExecutedAt,
  groupCellOwners,
  parseConId,
  parseGroupStatus,
  rowGroupId,
  rowGroupKey,
  serverSymbol,
} from "./view";

const NOW = Date.UTC(2026, 5, 21, 12, 0, 0);
const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();

function row(overrides: Partial<TradeExecutionRow>): TradeExecutionRow {
  return {
    id: 1,
    trade_id: 10,
    account_id: 1,
    account_alias: "DU1234567",
    ib_exec_id: "0000demo.1",
    exec_role: "single",
    sec_type: "FOP",
    executed_at: hoursAgo(1),
    quantity: 1,
    price: 10,
    side: "BOT",
    exchange: "CME",
    commission: null,
    realized_pnl: null,
    is_canonical: true,
    con_id: 100,
    contract_display: "ES Mar'27 6000 Call",
    parent_ib_exec_id: null,
    ib_codes: null,
    trade_ib_perm_id: null,
    trade_order_ref: null,
    trade_status: "filled",
    trade_lifecycle: null,
    trade_contract_display_name: null,
    trade_realized_pnl: null,
    trade_assigned_trade_group_id: null,
    trade_first_executed_at: null,
    trade_last_executed_at: null,
    ...overrides,
  };
}

describe("row identity", () => {
  test("settled rows group by trade, live fills by their combo parent or themselves", () => {
    expect(rowGroupKey(row({ trade_id: 7 }))).toBe("t:7");
    expect(
      rowGroupKey(
        row({ trade_id: null, ib_exec_id: "leg", parent_ib_exec_id: "bag" }),
      ),
    ).toBe("l:bag");
    expect(rowGroupKey(row({ trade_id: null, ib_exec_id: "solo" }))).toBe(
      "l:solo",
    );
  });

  test("group membership comes from the trade when settled, the fill when not", () => {
    expect(rowGroupId(row({ trade_assigned_trade_group_id: 3 }))).toBe(3);
    expect(
      rowGroupId(
        row({
          settled: false,
          live_trade_group_id: 9,
          trade_assigned_trade_group_id: 3,
        }),
      ),
    ).toBe(9);
    expect(rowGroupId(row({ settled: false }))).toBeNull();
  });
});

describe("URL filter parsing", () => {
  test("parseGroupStatus accepts only the two filters", () => {
    expect(parseGroupStatus("grouped")).toBe("grouped");
    expect(parseGroupStatus("ungrouped")).toBe("ungrouped");
    expect(parseGroupStatus("nope")).toBe("all");
    expect(parseGroupStatus(null)).toBe("all");
  });

  test("parseConId needs an integer", () => {
    expect(parseConId("123")).toBe(123);
    expect(parseConId("1.5")).toBeNull();
    expect(parseConId("x")).toBeNull();
    expect(parseConId(null)).toBeNull();
  });

  test("serverSymbol is only a plain alphanumeric token, uppercased", () => {
    expect(serverSymbol(" es ")).toBe("ES");
    expect(serverSymbol("ES.*Call")).toBeNull();
    expect(serverSymbol("")).toBeNull();
  });

  test("compileSymbolRegex is case-insensitive and tolerates a bad pattern", () => {
    expect(compileSymbolRegex("es")?.test("ES Mar'27")).toBe(true);
    expect(compileSymbolRegex("(")).toBeNull();
    expect(compileSymbolRegex("  ")).toBeNull();
  });
});

describe("filterExecutions", () => {
  const rows = [
    row({ id: 1, executed_at: hoursAgo(2), account_id: 1 }),
    row({
      id: 2,
      executed_at: hoursAgo(50),
      account_id: 2,
      account_alias: null,
      contract_display: "NQ Jun'26",
      trade_assigned_trade_group_id: 5,
    }),
    row({ id: 3, executed_at: hoursAgo(0.5), contract_display: "CL Jul'26" }),
    row({ id: 4, executed_at: "not a date" }),
  ];
  const all = { account: "all", symbol: "", timeRange: "all", groupStatus: "all" as const };

  test("no filters: newest first, unparseable dates last", () => {
    expect(filterExecutions(rows, all, NOW).map((r) => r.id)).toEqual([
      3, 1, 2, 4,
    ]);
  });

  test("account filter matches the id as a string", () => {
    expect(
      filterExecutions(rows, { ...all, account: "2" }, NOW).map((r) => r.id),
    ).toEqual([2]);
  });

  test("contract filter is a regex over the display name; invalid matches all", () => {
    expect(
      filterExecutions(rows, { ...all, symbol: "^(nq|cl)" }, NOW).map(
        (r) => r.id,
      ),
    ).toEqual([3, 2]);
    expect(filterExecutions(rows, { ...all, symbol: "(" }, NOW)).toHaveLength(4);
  });

  test("time range measures against the given clock and drops unparseable dates", () => {
    expect(
      filterExecutions(rows, { ...all, timeRange: "24h" }, NOW).map((r) => r.id),
    ).toEqual([3, 1]);
    expect(
      filterExecutions(rows, { ...all, timeRange: "3d" }, NOW).map((r) => r.id),
    ).toEqual([3, 1, 2]);
    expect(
      filterExecutions(rows, { ...all, timeRange: "bogus" }, NOW),
    ).toHaveLength(4);
  });

  test("group status splits on membership", () => {
    expect(
      filterExecutions(rows, { ...all, groupStatus: "grouped" }, NOW).map(
        (r) => r.id,
      ),
    ).toEqual([2]);
    expect(
      filterExecutions(rows, { ...all, groupStatus: "ungrouped" }, NOW).map(
        (r) => r.id,
      ),
    ).toEqual([3, 1, 4]);
  });
});

describe("accountOptions", () => {
  test("first-seen order with an alias fallback", () => {
    const options = accountOptions([
      row({ account_id: 2, account_alias: null }),
      row({ account_id: 1 }),
      row({ account_id: 2 }),
    ]);
    expect(options).toEqual([
      { id: "2", label: "Account 2" },
      { id: "1", label: "DU1234567" },
    ]);
  });
});

describe("groupCellOwners", () => {
  test("the combo summary owns its group even when a leg comes first", () => {
    const rows = [
      row({ id: 1, trade_id: 7, exec_role: "leg", executed_at: hoursAgo(3) }),
      row({
        id: 2,
        trade_id: 7,
        exec_role: "combo_summary",
        executed_at: hoursAgo(1),
      }),
    ];
    expect(groupCellOwners(rows).get("t:7")).toBe(2);
  });

  test("without a summary the earliest row owns the group", () => {
    const rows = [
      row({ id: 1, trade_id: 7, executed_at: hoursAgo(1) }),
      row({ id: 2, trade_id: 7, executed_at: hoursAgo(5) }),
      row({ id: 3, trade_id: 8, executed_at: hoursAgo(2) }),
    ];
    const owners = groupCellOwners(rows);
    expect(owners.get("t:7")).toBe(2);
    expect(owners.get("t:8")).toBe(3);
  });
});

describe("formatExecutedAt", () => {
  test("falls back to a hyphen", () => {
    expect(formatExecutedAt(null)).toBe("-");
    expect(formatExecutedAt("garbage")).toBe("-");
  });

  test("includes seconds", () => {
    const text = formatExecutedAt("2026-06-21T14:30:05Z");
    expect(text).toMatch(/\d{2}:\d{2}:\d{2}|\d{1,2}:\d{2}:\d{2}/);
  });
});
