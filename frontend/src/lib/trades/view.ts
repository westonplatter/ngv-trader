// Pure grouping, filtering, and ordering behind the Trades page.
//
// Kept out of the components so the behavior has a bun test: the repo has no
// DOM harness, so anything worth asserting must be a function over plain data.

import type { TradeExecutionRow } from "../../types/trades";

// ─── Row identity ────────────────────────────────────────────────────────────

// Effective trade-group membership for a row. Settled rows carry trade-level
// membership; unsettled live fills carry their own per-fill membership.
export function rowGroupId(row: TradeExecutionRow): number | null {
  return row.settled === false
    ? (row.live_trade_group_id ?? null)
    : row.trade_assigned_trade_group_id;
}

// The unit a row belongs to for display, grouping, and highlighting. Settled
// rows group by their parent trade; unsettled live fills have no trade, so a
// live combo groups by its BAG summary's ib_exec_id (legs carry it as
// parent_ib_exec_id). Standalone live fills are their own group.
export function rowGroupKey(row: TradeExecutionRow): string {
  if (row.trade_id !== null) return `t:${row.trade_id}`;
  return `l:${row.parent_ib_exec_id ?? row.ib_exec_id}`;
}

// What the Contract column shows for a row.
export function rowSymbol(row: TradeExecutionRow): string {
  return row.contract_display ?? row.trade_contract_display_name ?? "-";
}

// Date plus a seconds-precision time, in the browser locale. Executions within
// a combo land in the same second, so the seconds matter.
export function formatExecutedAt(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "-";
  const d = new Date(parsed);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  })}`;
}

// ─── URL-backed filters ──────────────────────────────────────────────────────

export type GroupStatus = "all" | "grouped" | "ungrouped";

export function parseGroupStatus(raw: string | null): GroupStatus {
  return raw === "grouped" || raw === "ungrouped" ? raw : "all";
}

export const TIME_RANGES: readonly { id: string; label: string }[] = [
  { id: "all", label: "All" },
  { id: "24h", label: "24h" },
  { id: "3d", label: "3d" },
  { id: "7d", label: "7d" },
  { id: "30d", label: "30d" },
  { id: "90d", label: "90d" },
];

const TIME_RANGE_HOURS: Record<string, number> = {
  "24h": 24,
  "3d": 72,
  "7d": 168,
  "30d": 720,
  "90d": 2160,
};

export interface TradeFilters {
  // Account id as a string, or "all".
  account: string;
  // Pattern typed into the Contract column header.
  symbol: string;
  // One of TIME_RANGES; anything unknown behaves like "all".
  timeRange: string;
  groupStatus: GroupStatus;
}

// The Contract pattern compiled case-insensitively. An invalid pattern (the
// operator is mid-keystroke) matches everything rather than nothing.
export function compileSymbolRegex(pattern: string): RegExp | null {
  const raw = pattern.trim();
  if (!raw) return null;
  try {
    return new RegExp(raw, "i");
  } catch {
    return null;
  }
}

// The symbol the server can pre-filter by: plain alphanumerics only. Anything
// else stays a client-side regex over the display name.
export function serverSymbol(pattern: string): string | null {
  const raw = pattern.trim();
  return /^[A-Za-z0-9]+$/.test(raw) ? raw.toUpperCase() : null;
}

export function parseConId(raw: string | null): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isInteger(parsed) ? parsed : null;
}

// ─── Filtering and ordering ──────────────────────────────────────────────────

// Rows passing the account, contract, time-range, and group-status filters,
// newest first. `nowMs` is the clock the relative ranges measure against; the
// caller takes it when rows arrive or the range changes, never during render.
export function filterExecutions(
  rows: TradeExecutionRow[],
  filters: TradeFilters,
  nowMs: number,
): TradeExecutionRow[] {
  let next = rows;
  if (filters.account !== "all") {
    next = next.filter((row) => String(row.account_id) === filters.account);
  }
  const symbolRegex = compileSymbolRegex(filters.symbol);
  if (symbolRegex) {
    next = next.filter((row) =>
      symbolRegex.test(
        row.contract_display ?? row.trade_contract_display_name ?? "",
      ),
    );
  }
  const hours = TIME_RANGE_HOURS[filters.timeRange];
  if (filters.timeRange !== "all" && hours) {
    const cutoff = nowMs - hours * 60 * 60 * 1000;
    next = next.filter((row) => Date.parse(row.executed_at) >= cutoff);
  }
  if (filters.groupStatus !== "all") {
    next = next.filter((row) =>
      filters.groupStatus === "grouped"
        ? rowGroupId(row) !== null
        : rowGroupId(row) === null,
    );
  }
  // Newest first by execution time, regardless of settled/unsettled — so the
  // most recent fills (including today's unsettled TWS fills) sit at the top.
  // Stable sort keeps same-timestamp combo/leg rows in their existing order.
  const execMs = (row: TradeExecutionRow) => {
    const t = Date.parse(row.executed_at);
    return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
  };
  return [...next].sort((a, b) => execMs(b) - execMs(a));
}

export interface AccountOption {
  id: string;
  label: string;
}

// Accounts present in the rows, in first-seen order, for the filter chips.
export function accountOptions(rows: TradeExecutionRow[]): AccountOption[] {
  const seen = new Map<string, string>();
  for (const row of rows) {
    const key = String(row.account_id);
    if (!seen.has(key)) {
      seen.set(key, row.account_alias ?? `Account ${row.account_id}`);
    }
  }
  return Array.from(seen.entries()).map(([id, label]) => ({ id, label }));
}

// For each group (settled trade or live combo), the row that owns the Trade
// Group, Tags, and Tasks cells. Prefer combo_summary; otherwise the earliest
// row in the filtered view. One cell per group, so a spread is grouped as one
// trade rather than once per leg.
export function groupCellOwners(rows: TradeExecutionRow[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const row of rows) {
    if (row.exec_role === "combo_summary") {
      map.set(rowGroupKey(row), row.id);
    }
  }
  for (const row of rows) {
    const key = rowGroupKey(row);
    if (!map.has(key)) {
      map.set(key, row.id);
    } else {
      const currentId = map.get(key)!;
      const current = rows.find((r) => r.id === currentId);
      if (
        current &&
        current.exec_role !== "combo_summary" &&
        Date.parse(row.executed_at) < Date.parse(current.executed_at)
      ) {
        map.set(key, row.id);
      }
    }
  }
  return map;
}
