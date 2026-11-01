// Pure filtering, sorting, and totals behind the Positions page.
//
// Kept out of the components so the behavior has a bun test: the repo has no
// DOM harness, so anything worth asserting must be a function over plain data.

import type { Position } from "../../types/positions";
import type { ItemRef } from "../../types/tags";
import { formatExpiry } from "../../utils/date";
import {
  nextSortState,
  sortRows,
  type SortState as TableSortState,
} from "../tableSort";

// ─── Sorting ─────────────────────────────────────────────────────────────────

export type SortColumn =
  | "symbol"
  | "local_symbol"
  | "option_expiry_date"
  | "dte";

export const SORTABLE_COLUMNS: readonly SortColumn[] = [
  "symbol",
  "local_symbol",
  "option_expiry_date",
  "dte",
];

export function isSortableColumn(key: keyof Position): key is SortColumn {
  return (SORTABLE_COLUMNS as readonly string[]).includes(key);
}

export type SortState = TableSortState<SortColumn>;

export const DEFAULT_SORT: SortState = { column: "symbol", direction: "asc" };

// What a header click does: the shared cycle (see lib/tableSort.ts). Every
// sortable column here is a name or a date, so each starts ascending (nearest
// expiry and lowest DTE first), then flips, then clears.
export function nextSort(current: SortState, clicked: SortColumn): SortState {
  return nextSortState(current, clicked, { ascendingFirst: SORTABLE_COLUMNS });
}

// Expiry as a sortable YYYYMMDD number; null when missing or not a date.
function expirySortValue(p: Position): number | null {
  const raw = (p.option_expiry_date ?? p.last_trade_date ?? "").trim();
  if (!raw) return null;
  const digits = raw.includes("-") ? raw.replaceAll("-", "") : raw;
  return /^\d{8}$/.test(digits) ? Number(digits) : null;
}

function sortValueFor(p: Position, column: SortColumn): string | number | null {
  if (column === "symbol") return p.symbol ? p.symbol.toUpperCase() : null;
  if (column === "local_symbol")
    return p.local_symbol ? p.local_symbol.toUpperCase() : null;
  if (column === "option_expiry_date") return expirySortValue(p);
  return p.dte;
}

// A sorted copy. Ties break on con_id (in either direction) so the order is
// stable across reloads.
export function sortPositions(rows: Position[], sort: SortState): Position[] {
  return sortRows(rows, sort, sortValueFor, (a, b) => a.con_id - b.con_id);
}

// ─── Filtering ───────────────────────────────────────────────────────────────

export interface PositionFilters {
  // Account alias, or "all".
  account: string;
  // Regex (case-insensitive); a pattern that fails to compile falls back to a
  // substring match so a half-typed filter never throws.
  symbol: string;
  localSymbol: string;
  secType: string;
  // Raw input text; parsed with parseDte. Blank means unbounded.
  dteMin: string;
  dteMax: string;
}

export const EMPTY_FILTERS: PositionFilters = {
  account: "all",
  symbol: "",
  localSymbol: "",
  secType: "",
  dteMin: "",
  dteMax: "",
};

export function parseDte(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function regexMatch(
  value: string | null | undefined,
  pattern: string,
): boolean {
  if (!pattern) return true;
  const str = value ?? "";
  try {
    return new RegExp(pattern, "i").test(str);
  } catch {
    return str.toLowerCase().includes(pattern.toLowerCase());
  }
}

// Rows passing every filter. With either DTE bound set, rows without a DTE
// (stock, futures) drop out; with neither set they stay.
export function filterPositions(
  positions: Position[],
  filters: PositionFilters,
): Position[] {
  const dteMin = parseDte(filters.dteMin);
  const dteMax = parseDte(filters.dteMax);
  return positions.filter((p) => {
    const dteMatches =
      dteMin === null && dteMax === null
        ? true
        : p.dte !== null &&
          (dteMin === null || p.dte >= dteMin) &&
          (dteMax === null || p.dte <= dteMax);
    return (
      (filters.account === "all" || p.account_alias === filters.account) &&
      regexMatch(p.symbol, filters.symbol) &&
      regexMatch(p.local_symbol, filters.localSymbol) &&
      regexMatch(p.sec_type, filters.secType) &&
      dteMatches
    );
  });
}

export function accountAliases(positions: Position[]): string[] {
  const seen = new Set<string>();
  for (const p of positions) seen.add(p.account_alias);
  return Array.from(seen).sort();
}

// ─── Per-row helpers ─────────────────────────────────────────────────────────

// A row's live overlay is usable only when it's live-sourced AND not stale.
export function isLiveFresh(pos: Position): boolean {
  return pos.source === "live" && !pos.live_is_stale;
}

// The expiry column: options prefer the option expiry, futures the last trade
// date, everything else whichever is present.
export function expiryForPosition(pos: Position): string {
  const secType = (pos.sec_type ?? "").toUpperCase();
  if (secType === "OPT" || secType === "FOP") {
    return formatExpiry(pos.option_expiry_date ?? pos.last_trade_date);
  }
  if (secType === "FUT") {
    return formatExpiry(pos.last_trade_date);
  }
  return formatExpiry(pos.option_expiry_date ?? pos.last_trade_date);
}

// Entry cost basis for a position, derived as current value − unrealized gain.
// Used only for privacy-mode relative returns; null when either input is
// missing so the caller can fall back to masking.
export function positionCostBasis(pos: Position): number | null {
  if (pos.position_value == null || pos.fifo_pnl_unrealized == null) {
    return null;
  }
  return pos.position_value - pos.fifo_pnl_unrealized;
}

export function positionItem(pos: Position): ItemRef {
  return {
    entity_type: "position",
    account_id: pos.account_id,
    con_id: pos.con_id,
  };
}

// ─── Totals ──────────────────────────────────────────────────────────────────

export interface PositionTotals {
  // Sum of settled unrealized P&L; null when no row has one.
  unrealized: number | null;
  // Live unrealized where the overlay is fresh, settled otherwise.
  liveUnrealized: number | null;
  // Aggregate entry cost for privacy-mode relative returns: value − gain, so
  // no dollar figure is exposed, only the ratio.
  costBasis: number | null;
  // Newest fresh live mark across the rows, for the "live as of" note.
  newestMarkTs: string | null;
}

export function positionTotals(rows: Position[]): PositionTotals {
  let unrealized = 0;
  let anyUnrealized = false;
  let live = 0;
  let anyLive = false;
  let basis = 0;
  let anyBasis = false;
  let newest: string | null = null;
  for (const p of rows) {
    if (p.fifo_pnl_unrealized != null) {
      unrealized += p.fifo_pnl_unrealized;
      anyUnrealized = true;
    }
    const liveVal = isLiveFresh(p) ? p.live_unrealized : p.fifo_pnl_unrealized;
    if (liveVal != null) {
      live += liveVal;
      anyLive = true;
    }
    if (p.position_value != null && p.fifo_pnl_unrealized != null) {
      basis += p.position_value - p.fifo_pnl_unrealized;
      anyBasis = true;
    }
    if (isLiveFresh(p) && p.mark_ts && (newest == null || p.mark_ts > newest)) {
      newest = p.mark_ts;
    }
  }
  return {
    unrealized: anyUnrealized ? unrealized : null,
    liveUnrealized: anyLive ? live : null,
    costBasis: anyBasis ? basis : null,
    newestMarkTs: newest,
  };
}
