import { describe, expect, test } from "bun:test";
import {
  applyParamUpdates,
  countByTab,
  formatWhen,
  itemsForTab,
  parseTab,
  sortTagsByValue,
  splitList,
} from "./tagBrowser";
import type { Tag, TaggedItem } from "../types/tags";

function item(entity_type: string, id: number): TaggedItem {
  return {
    entity_type,
    id,
    label: `${entity_type}-${id}`,
    tags: [],
    details: {},
  } as unknown as TaggedItem;
}

describe("splitList", () => {
  test("splits on commas and drops empty pieces", () => {
    expect(splitList("a,b,,c")).toEqual(["a", "b", "c"]);
    expect(splitList("")).toEqual([]);
  });
});

describe("parseTab", () => {
  test("defaults to trades", () => {
    expect(parseTab(null)).toBe("trades");
    expect(parseTab("tasks")).toBe("tasks");
  });
});

describe("applyParamUpdates", () => {
  test("sets, joins lists, and deletes empty values without mutating the input", () => {
    const prev = new URLSearchParams("all=x&tab=tasks");
    const next = applyParamUpdates(prev, { all: ["a", "b"], tab: "", any: [] });
    expect(next.get("all")).toBe("a,b");
    expect(next.has("tab")).toBe(false);
    expect(next.has("any")).toBe(false);
    expect(prev.toString()).toBe("all=x&tab=tasks");
  });

  test("applies several keys in one update", () => {
    const next = applyParamUpdates(new URLSearchParams(), {
      all: ["t"],
      any: [],
      none: [],
    });
    expect(next.toString()).toBe("all=t");
  });
});

describe("sortTagsByValue", () => {
  test("orders case-insensitively and leaves the input alone", () => {
    const rows = [
      { value: "beta" },
      { value: "Alpha" },
      { value: "alpine" },
    ] as Tag[];
    expect(sortTagsByValue(rows).map((t) => t.value)).toEqual([
      "Alpha",
      "alpine",
      "beta",
    ]);
    expect(rows[0].value).toBe("beta");
  });
});

describe("tabs", () => {
  const items = [
    item("trade", 1),
    item("live_execution", 2),
    item("position", 3),
    item("trade_group", 4),
    item("trade_group", 5),
  ];

  test("itemsForTab groups the trade kinds under Trades", () => {
    expect(itemsForTab(items, "trades").map((i) => i.label)).toEqual([
      "trade-1",
      "live_execution-2",
    ]);
    expect(itemsForTab(items, "tasks")).toEqual([]);
  });

  test("countByTab counts every tab", () => {
    expect(countByTab(items)).toEqual({
      trades: 2,
      positions: 1,
      trade_groups: 2,
      tasks: 0,
    });
  });
});

describe("formatWhen", () => {
  test("is blank for non-strings and unparsable text", () => {
    expect(formatWhen(undefined)).toBe("");
    expect(formatWhen(5)).toBe("");
    expect(formatWhen("not a date")).toBe("");
  });

  test("formats a valid ISO timestamp", () => {
    expect(formatWhen("2026-01-02T03:04:05Z")).toBe(
      new Date("2026-01-02T03:04:05Z").toLocaleString(),
    );
  });
});
