// Pure logic behind the Strategy P&L table.
//
// Kept out of the component so it can be tested without a DOM: the repo has no
// component-test harness, so anything worth asserting has to be a function over
// plain data.

import type { TradeGroupPnlRow } from "./tradeGroups";

export type SortColumn =
  | "strategy"
  | "group"
  | "realized"
  | "unrealized"
  | "total";
export type SortDirection = "asc" | "desc" | "none";

export interface SortState {
  column: SortColumn | null;
  direction: SortDirection;
}

const TEXT_COLUMNS: readonly SortColumn[] = ["strategy", "group"];

export const NO_SORT: SortState = { column: null, direction: "none" };

// Default view: strategy a-z, then group name a-z within it. Reading down the
// Strategy column is how the desk scans the book, so a name ordering beats the
// endpoint's created_at ordering as a landing state.
export const DEFAULT_SORT: SortState = { column: "strategy", direction: "asc" };

export const NO_STRATEGY_LABEL = "No Strategy";
export const EMPTY_CELL = "—";

/**
 * Advance the sort state for a header click.
 *
 * A name column starts ascending (a-z is what one click on a name should give,
 * and it matches the landing state); a P&L column starts descending, because
 * biggest-first is the useful end and a fresh ascending sort would bury the
 * movers. Either way the same column then flips and finally clears — the same
 * three-state behavior as the Positions table.
 */
export function nextSortState(
  current: SortState,
  column: SortColumn,
): SortState {
  const first: SortDirection = TEXT_COLUMNS.includes(column) ? "asc" : "desc";
  const second: SortDirection = first === "asc" ? "desc" : "asc";
  if (current.column !== column) return { column, direction: first };
  if (current.direction === first) return { column, direction: second };
  if (current.direction === second) return NO_SORT;
  return { column, direction: first };
}

export function sortIndicator(state: SortState, column: SortColumn): string {
  if (state.column !== column || state.direction === "none") return "↕";
  return state.direction === "asc" ? "↑" : "↓";
}

export function ariaSort(
  state: SortState,
  column: SortColumn,
): "ascending" | "descending" | "none" {
  if (state.column !== column || state.direction === "none") return "none";
  return state.direction === "asc" ? "ascending" : "descending";
}

/**
 * The three P&L figures for a row, all drawn from the same layer.
 *
 * The intraday figures win whenever any of them is present; otherwise the
 * settled ones do. Mixing layers per column would let Total stop reconciling to
 * Realized + Unrealized, which reads as a bug in the arithmetic.
 */
export function resolvePnl(row: TradeGroupPnlRow): {
  total: number | null;
  realized: number | null;
  unrealized: number | null;
  live: boolean;
} {
  const live =
    row.intraday_total_pnl != null ||
    row.intraday_realized_pnl != null ||
    row.intraday_unrealized_pnl != null;
  if (live) {
    return {
      total: row.intraday_total_pnl,
      realized: row.intraday_realized_pnl,
      unrealized: row.intraday_unrealized_pnl,
      live: true,
    };
  }
  return {
    total: row.total_pnl,
    realized: row.realized_pnl,
    unrealized: row.unrealized_pnl,
    live: false,
  };
}

function sortValue(
  row: TradeGroupPnlRow,
  column: SortColumn,
): string | number | null {
  // Untagged groups have no strategy to sort by; null sends them to the bottom
  // rather than interleaving a placeholder label under "N".
  if (column === "strategy") return row.primary_strategy_value;
  if (column === "group") return row.name;
  const resolved = resolvePnl(row);
  if (column === "realized") return resolved.realized;
  if (column === "unrealized") return resolved.unrealized;
  return resolved.total;
}

function compare(left: string | number, right: string | number): number {
  if (typeof left === "number" && typeof right === "number")
    return left - right;
  return String(left).localeCompare(String(right), undefined, {
    sensitivity: "base",
  });
}

/**
 * Sort by one column, keeping rows with no value at the bottom either way.
 *
 * A group with no P&L data is not a zero and an untagged group is not an empty
 * strategy name — treating either as a value would rank it above real ones.
 * Ties break on the group name in the same direction as the sort — so the
 * default (strategy a-z) reads group names a-z beneath each strategy — and then
 * on the id, which only makes the order deterministic.
 */
export function sortRows(
  rows: readonly TradeGroupPnlRow[],
  state: SortState,
): TradeGroupPnlRow[] {
  const sorted = [...rows];
  if (state.column === null || state.direction === "none") return sorted;
  const column = state.column;
  const factor = state.direction === "desc" ? -1 : 1;
  sorted.sort((a, b) => {
    const left = sortValue(a, column);
    const right = sortValue(b, column);
    if (left !== null && right !== null) {
      const cmp = compare(left, right);
      if (cmp !== 0) return cmp * factor;
    } else if (left === null && right !== null) {
      return 1;
    } else if (right === null && left !== null) {
      return -1;
    }
    const byName = compare(a.name, b.name) * factor;
    return byName !== 0 ? byName : a.id - b.id;
  });
  return sorted;
}

export interface StrategyPnlFilters {
  status: string;
  accountId: string;
  instrument: string;
}

/**
 * Query string for `GET /trade-groups`.
 *
 * Absent filters are omitted entirely rather than sent blank — an empty
 * `instrument=` would reach the backend as a pattern and 400.
 */
export function buildTradeGroupsQuery(filters: StrategyPnlFilters): string {
  const params = new URLSearchParams();
  params.set("include_intraday", "true");
  if (filters.status && filters.status !== "all")
    params.set("status", filters.status);
  if (filters.accountId && filters.accountId !== "all")
    params.set("account_id", filters.accountId);
  const instrument = filters.instrument.trim();
  if (instrument) params.set("instrument", instrument);
  return params.toString();
}

export type FreshnessTone = "live" | "stale" | "none";

export interface Freshness {
  label: string;
  tone: FreshnessTone;
  title: string;
}

function markTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "";
  return new Date(parsed).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** How current the row's marks are, matching the Strategies/Positions wording. */
export function formatFreshness(
  marksAsOf: string | null,
  liveIsStale: boolean,
): Freshness {
  if (!marksAsOf) {
    return {
      label: "settled",
      tone: "none",
      title:
        "No live TWS data for this group — figures are the settled snapshot.",
    };
  }
  const time = markTime(marksAsOf);
  if (liveIsStale) {
    return {
      label: time ? `stale ${time}` : "stale",
      tone: "stale",
      title:
        "Every live mark behind this group is older than the latest settled snapshot. Refresh Live (TWS) to update.",
    };
  }
  return {
    label: time ? `live ${time}` : "live",
    tone: "live",
    title: "Live TWS marks are current.",
  };
}

/** Instruments cell: a plain symbol, a comma-joined list, or the em-dash. */
export function formatInstruments(instruments: string[] | null): string {
  if (!instruments || instruments.length === 0) return EMPTY_CELL;
  return instruments.join(", ");
}

/** Strategy cell, falling back to the same wording as `tradeGroupLabel`. */
export function strategyLabel(row: TradeGroupPnlRow): string {
  return row.primary_strategy_value ?? NO_STRATEGY_LABEL;
}
