// Shared sort state machine and row sorting.
import { describe, expect, test } from "bun:test";

import {
  ariaSort,
  nextSortState,
  noSort,
  sortIndicator,
  sortRows,
  type SortState,
} from "./tableSort";

type Col = "name" | "date" | "amount";
const OPTIONS = { ascendingFirst: ["name", "date"] as readonly Col[] };
const NONE: SortState<Col> = noSort<Col>();

describe("nextSortState", () => {
  test("an ascending-first column goes asc -> desc -> cleared", () => {
    const first = nextSortState(NONE, "name", OPTIONS);
    expect(first).toEqual({ column: "name", direction: "asc" });
    const second = nextSortState(first, "name", OPTIONS);
    expect(second).toEqual({ column: "name", direction: "desc" });
    expect(nextSortState(second, "name", OPTIONS)).toEqual(NONE);
  });

  test("any other column goes desc -> asc -> cleared", () => {
    const first = nextSortState(NONE, "amount", OPTIONS);
    expect(first).toEqual({ column: "amount", direction: "desc" });
    const second = nextSortState(first, "amount", OPTIONS);
    expect(second).toEqual({ column: "amount", direction: "asc" });
    expect(nextSortState(second, "amount", OPTIONS)).toEqual(NONE);
  });

  test("the first click on a new column sorts immediately", () => {
    const state: SortState<Col> = { column: "name", direction: "desc" };
    expect(nextSortState(state, "amount", OPTIONS)).toEqual({
      column: "amount",
      direction: "desc",
    });
    expect(nextSortState(state, "date", OPTIONS)).toEqual({
      column: "date",
      direction: "asc",
    });
  });

  test("clicking the sorted column advances it, not resets it", () => {
    const state: SortState<Col> = { column: "name", direction: "asc" };
    expect(nextSortState(state, "name", OPTIONS).direction).toBe("desc");
  });

  test("a selected column with no direction restarts at its first", () => {
    const state: SortState<Col> = { column: "amount", direction: "none" };
    expect(nextSortState(state, "amount", OPTIONS)).toEqual({
      column: "amount",
      direction: "desc",
    });
  });

  test("accepts a Set of ascending-first columns", () => {
    const options = { ascendingFirst: new Set<Col>(["date"]) };
    expect(nextSortState(NONE, "date", options).direction).toBe("asc");
    expect(nextSortState(NONE, "name", options).direction).toBe("desc");
  });
});

describe("sortIndicator and ariaSort", () => {
  const asc: SortState<Col> = { column: "name", direction: "asc" };
  const desc: SortState<Col> = { column: "name", direction: "desc" };

  test("show the direction on the sorted column", () => {
    expect(sortIndicator(asc, "name")).toBe("↑");
    expect(sortIndicator(desc, "name")).toBe("↓");
    expect(ariaSort(asc, "name")).toBe("ascending");
    expect(ariaSort(desc, "name")).toBe("descending");
  });

  test("show the neutral marker on other columns and when cleared", () => {
    expect(sortIndicator(asc, "date")).toBe("↕");
    expect(ariaSort(asc, "date")).toBe("none");
    expect(sortIndicator(NONE, "name")).toBe("↕");
    expect(ariaSort(NONE, "name")).toBe("none");
    const selected: SortState<Col> = { column: "name", direction: "none" };
    expect(sortIndicator(selected, "name")).toBe("↕");
    expect(ariaSort(selected, "name")).toBe("none");
  });
});

describe("sortRows", () => {
  interface Row {
    id: number;
    name: string | null;
    amount: number | null;
  }
  const value = (row: Row, column: Col) =>
    column === "amount" ? row.amount : row.name;
  const byId = (a: Row, b: Row) => a.id - b.id;
  const rows: Row[] = [
    { id: 1, name: "beta", amount: 5 },
    { id: 2, name: "Alpha", amount: null },
    { id: 3, name: null, amount: 5 },
    { id: 4, name: "alpha", amount: 9 },
  ];
  const ids = (list: Row[]) => list.map((r) => r.id);

  test("returns a copy in input order when unsorted", () => {
    const out = sortRows(rows, NONE, value);
    expect(ids(out)).toEqual([1, 2, 3, 4]);
    expect(out).not.toBe(rows);
  });

  test("compares text case-insensitively, rows without a value last", () => {
    const asc = sortRows(
      rows,
      { column: "name", direction: "asc" },
      value,
      byId,
    );
    expect(ids(asc)).toEqual([2, 4, 1, 3]);
    const desc = sortRows(
      rows,
      { column: "name", direction: "desc" },
      value,
      byId,
    );
    expect(ids(desc)).toEqual([1, 2, 4, 3]);
  });

  test("compares numbers numerically, rows without a value last", () => {
    const asc = sortRows(
      rows,
      { column: "amount", direction: "asc" },
      value,
      byId,
    );
    expect(ids(asc)).toEqual([1, 3, 4, 2]);
    const desc = sortRows(
      rows,
      { column: "amount", direction: "desc" },
      value,
      byId,
    );
    expect(ids(desc)).toEqual([4, 1, 3, 2]);
  });

  test("the tie-break is told the direction as +1 or -1", () => {
    const seen: number[] = [];
    const record = (a: Row, b: Row, factor: 1 | -1) => {
      seen.push(factor);
      return (a.id - b.id) * factor;
    };
    const desc = sortRows(
      rows,
      { column: "amount", direction: "desc" },
      value,
      record,
    );
    // 1 and 3 tie on amount 5; following the direction puts 3 first.
    expect(ids(desc)).toEqual([4, 3, 1, 2]);
    expect(seen.every((f) => f === -1)).toBe(true);
  });

  test("without a tie-break, ties keep input order", () => {
    const out = sortRows(rows, { column: "amount", direction: "desc" }, value);
    expect(ids(out)).toEqual([4, 1, 3, 2]);
  });

  test("does not mutate the input", () => {
    const before = ids(rows);
    sortRows(rows, { column: "name", direction: "asc" }, value);
    expect(ids(rows)).toEqual(before);
  });
});
