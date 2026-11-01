import { describe, expect, test } from "bun:test";
import type { TradeGroup } from "../../types/tradeGroups";
import {
  groupSections,
  parseIdParam,
  resolveSelection,
  sortStrategies,
} from "./groups";

function group(overrides: Partial<TradeGroup>): TradeGroup {
  return {
    id: 1,
    account_id: null,
    name: "G",
    status: "open",
    primary_strategy_value: "core",
    total_pnl: null,
    realized_pnl: null,
    unrealized_pnl: null,
    intraday_unrealized_pnl: null,
    intraday_realized_pnl: null,
    intraday_total_pnl: null,
    marks_as_of: null,
    live_is_stale: false,
    instruments: null,
    notes: null,
    meta_yaml: null,
    opened_at: "2026-06-01T00:00:00Z",
    closed_at: null,
    opened_by: null,
    closed_by: null,
    ...overrides,
  };
}

const GROUPS: TradeGroup[] = [
  group({ id: 1, name: "b group", status: "open", opened_at: "2026-06-02T00:00:00Z" }),
  group({ id: 2, name: "A group", status: "closed", opened_at: "2026-06-05T00:00:00Z" }),
  group({ id: 3, name: "group 10", status: "open", opened_at: "2026-06-01T00:00:00Z" }),
  group({ id: 4, name: "group 9", status: "archived", opened_at: "2026-06-03T00:00:00Z" }),
];

describe("groupSections", () => {
  test("flat A–Z sort is one unlabeled block, case-insensitive and natural-numeric", () => {
    const sections = groupSections(GROUPS, "all", "name");
    expect(sections).toHaveLength(1);
    expect(sections[0].status).toBeNull();
    expect(sections[0].groups.map((g) => g.name)).toEqual([
      "A group",
      "b group",
      "group 9",
      "group 10",
    ]);
  });

  test("grouped sort splits Open → Closed → Archived and drops empty sections", () => {
    const sections = groupSections(GROUPS, "all", "name_grouped");
    expect(sections.map((s) => s.status)).toEqual(["open", "closed", "archived"]);
    expect(sections[0].groups.map((g) => g.id)).toEqual([1, 3]);
    const onlyOpen = groupSections(
      GROUPS.filter((g) => g.status === "open"),
      "all",
      "name_grouped",
    );
    expect(onlyOpen.map((s) => s.status)).toEqual(["open"]);
  });

  test("the Active filter means open; a status filter narrows to that status", () => {
    expect(
      groupSections(GROUPS, "active", "name").flatMap((s) => s.groups.map((g) => g.id)),
    ).toEqual([1, 3]);
    expect(
      groupSections(GROUPS, "archived", "name_grouped").map((s) => s.status),
    ).toEqual(["archived"]);
    expect(groupSections(GROUPS, "closed", "name")).toHaveLength(1);
  });

  test("opened_at sorts newest first, name breaking ties", () => {
    const sections = groupSections(GROUPS, "all", "opened_at");
    expect(sections[0].groups.map((g) => g.id)).toEqual([2, 4, 1, 3]);
    const tied = groupSections(
      [
        group({ id: 1, name: "z", opened_at: "2026-06-01T00:00:00Z" }),
        group({ id: 2, name: "a", opened_at: "2026-06-01T00:00:00Z" }),
      ],
      "all",
      "opened_at",
    );
    expect(tied[0].groups.map((g) => g.id)).toEqual([2, 1]);
  });

  test("no in-scope groups yields no sections", () => {
    expect(groupSections([], "all", "name")).toEqual([]);
    expect(groupSections(GROUPS, "closed", "opened_at_grouped")).toHaveLength(1);
  });
});

describe("sortStrategies", () => {
  test("orders by name, case-insensitively, without mutating", () => {
    const raw = [
      { id: 1, name: "beta", normalized_name: "beta", created_by: "u", created_at: "", archived_at: null },
      { id: 2, name: "Alpha", normalized_name: "alpha", created_by: "u", created_at: "", archived_at: null },
    ];
    expect(sortStrategies(raw).map((s) => s.id)).toEqual([2, 1]);
    expect(raw.map((s) => s.id)).toEqual([1, 2]);
  });
});

describe("parseIdParam", () => {
  test("parses integers and rejects the rest", () => {
    expect(parseIdParam("12")).toBe(12);
    expect(parseIdParam("12abc")).toBe(12);
    expect(parseIdParam("abc")).toBeNull();
    expect(parseIdParam("")).toBeNull();
    expect(parseIdParam(null)).toBeNull();
  });
});

describe("resolveSelection", () => {
  const items = [{ id: 5 }, { id: 7 }];
  test("keeps a selection that is still present", () => {
    expect(resolveSelection(7, items)).toBe(7);
  });
  test("falls back to the first item when the selection is gone or unset", () => {
    expect(resolveSelection(9, items)).toBe(5);
    expect(resolveSelection(null, items)).toBe(5);
  });
  test("is null for an empty list", () => {
    expect(resolveSelection(5, [])).toBeNull();
  });
});
