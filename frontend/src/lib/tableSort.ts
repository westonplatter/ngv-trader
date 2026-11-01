// Sort state machine and row sorting shared by the sortable tables.
//
// The Strategy P&L and Positions tables used to carry their own copies, and
// their header-click cycles disagreed (Positions' first click on a new column
// selected it without ordering anything). One implementation, generic over the
// table's column union, keeps the cycle the same everywhere. Pure functions
// over plain data so the behavior has a bun test; the repo has no DOM harness.

export type SortDirection = "asc" | "desc" | "none";

export interface SortState<C extends string> {
  column: C | null;
  direction: SortDirection;
}

/** The cleared state: no column selected, rows in input order. */
export function noSort<C extends string>(): SortState<C> {
  return { column: null, direction: "none" };
}

/** The shape every table's column declaration shares. */
export interface ColumnDef<K extends string> {
  key: K;
  label: string;
}

export interface NextSortOptions<C extends string> {
  /**
   * Columns whose first click sorts ascending (names, dates). Any other column
   * starts descending, because biggest-first is the useful end of a number and
   * an ascending sort would bury the movers.
   */
  ascendingFirst: ReadonlySet<C> | readonly C[];
}

function isAscendingFirst<C extends string>(
  options: NextSortOptions<C>,
  column: C,
): boolean {
  const columns = options.ascendingFirst;
  return "has" in columns ? columns.has(column) : columns.includes(column);
}

/**
 * Advance the sort state for a header click.
 *
 * A click on a different column sorts by it immediately in that column's first
 * direction; further clicks on the same column flip it and then clear it.
 */
export function nextSortState<C extends string>(
  current: SortState<C>,
  column: C,
  options: NextSortOptions<C>,
): SortState<C> {
  const first: SortDirection = isAscendingFirst(options, column)
    ? "asc"
    : "desc";
  const second: SortDirection = first === "asc" ? "desc" : "asc";
  if (current.column !== column) return { column, direction: first };
  if (current.direction === first) return { column, direction: second };
  if (current.direction === second) return noSort();
  return { column, direction: first };
}

export function sortIndicator<C extends string>(
  state: SortState<C>,
  column: C,
): string {
  if (state.column !== column || state.direction === "none") return "↕";
  return state.direction === "asc" ? "↑" : "↓";
}

export function ariaSort<C extends string>(
  state: SortState<C>,
  column: C,
): "ascending" | "descending" | "none" {
  if (state.column !== column || state.direction === "none") return "none";
  return state.direction === "asc" ? "ascending" : "descending";
}

export type SortValue = string | number;

/** Numbers numerically, everything else case-insensitively as text. */
export function compareValues(left: SortValue, right: SortValue): number {
  if (typeof left === "number" && typeof right === "number")
    return left - right;
  return String(left).localeCompare(String(right), undefined, {
    sensitivity: "base",
  });
}

/**
 * Sort a copy of `rows` by the selected column.
 *
 * A row with no value (`null`) goes to the bottom in either direction: a
 * missing figure is not a zero and a missing name is not an empty string, so
 * ranking it among real values would mislead. Rows that tie, or both have no
 * value, fall to `tieBreak`, which receives +1 for ascending and -1 for
 * descending so a caller can follow the sort direction or ignore it. Without
 * one, ties keep their input order.
 */
export function sortRows<Row, C extends string>(
  rows: readonly Row[],
  state: SortState<C>,
  sortValue: (row: Row, column: C) => SortValue | null,
  tieBreak?: (a: Row, b: Row, factor: 1 | -1) => number,
): Row[] {
  const sorted = [...rows];
  if (state.column === null || state.direction === "none") return sorted;
  const column = state.column;
  const factor = state.direction === "desc" ? -1 : 1;
  sorted.sort((a, b) => {
    const left = sortValue(a, column);
    const right = sortValue(b, column);
    if (left !== null && right !== null) {
      const cmp = compareValues(left, right);
      if (cmp !== 0) return cmp * factor;
    } else if (left === null && right !== null) {
      return 1;
    } else if (right === null && left !== null) {
      return -1;
    }
    return tieBreak ? tieBreak(a, b, factor) : 0;
  });
  return sorted;
}
