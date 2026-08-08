import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK, formatRelativeReturn } from "../utils/privacy";
import { API_BASE_URL } from "../config";
import { useSSE } from "../lib/events";
import {
  formatDelta,
  formatGreek,
  formatMoney,
  formatMultiplier,
  formatPercent,
  formatStrike,
} from "../utils/number";
import TradeGroupSearchSelect from "./TradeGroupSearchSelect";

export interface TradeGroupRef {
  id: number;
  name: string;
}

export interface Position {
  id: number;
  account_id: number;
  account_alias: string;
  contract_display_name: string;
  con_id: number;
  trade_groups: TradeGroupRef[];
  symbol: string | null;
  sec_type: string | null;
  exchange: string | null;
  primary_exchange: string | null;
  currency: string | null;
  local_symbol: string | null;
  trading_class: string | null;
  last_trade_date: string | null;
  option_expiry_date: string | null;
  dte: number | null;
  strike: number | null;
  right: string | null;
  multiplier: string | null;
  position: number;
  avg_cost: number;
  mark_price: number | null;
  position_value: number | null;
  fifo_pnl_unrealized: number | null;
  fetched_at: string;
  // Intraday overlay (additive): live current-state fields.
  source: string;
  mark: number | null;
  mark_ts: string | null;
  live_unrealized: number | null;
  // Staleness of the live TWS overlay: true when the settled FlexQuery snapshot
  // was loaded more recently than the live snapshot. When stale, the overlay
  // columns are blanked and the freshness badge reads "stale" (not green "live").
  live_fetched_at: string | null;
  live_is_stale: boolean;
  // Live option metrics (additive; from the separate option-metrics sync job).
  // null for non-options or when that job hasn't run.
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  und_price: number | null;
  intrinsic_value: number | null;
  extrinsic_value: number | null;
}

function formatMarkTime(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

type SortDirection = "none" | "desc" | "asc";
type SortColumn = "symbol" | "local_symbol" | "option_expiry_date" | "dte";

function formatExpiry(value: string | null | undefined): string {
  if (!value) return "\u2014";
  // YYYYMMDD → YYYY-MM-DD
  if (value.length === 8 && !value.includes("-")) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function expiryForPosition(pos: Position): string {
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
function positionCostBasis(pos: Position): number | null {
  if (pos.position_value == null || pos.fifo_pnl_unrealized == null) {
    return null;
  }
  return pos.position_value - pos.fifo_pnl_unrealized;
}

const COLUMNS: { key: keyof Position; label: string }[] = [
  { key: "con_id", label: "Con ID" },
  { key: "account_alias", label: "Account" },
  { key: "trade_groups", label: "Trade Group" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "contract_display_name", label: "Contract" },
  { key: "local_symbol", label: "Local Symbol" },
  { key: "last_trade_date", label: "Last Trade Date" },
  { key: "option_expiry_date", label: "Expiry" },
  { key: "dte", label: "DTE" },
  { key: "strike", label: "Strike" },
  { key: "right", label: "Call/Put" },
  { key: "multiplier", label: "Multiplier" },
  { key: "position", label: "Position" },
  { key: "avg_cost", label: "Avg Cost" },
  { key: "mark_price", label: "Mark" },
  { key: "position_value", label: "Value" },
  { key: "fifo_pnl_unrealized", label: "Unrealized PnL" },
  { key: "mark", label: "Live Mark" },
  { key: "live_unrealized", label: "Live Unrealized" },
  { key: "iv", label: "IV" },
  { key: "delta", label: "Delta" },
  { key: "gamma", label: "Gamma" },
  { key: "theta", label: "Theta" },
  { key: "vega", label: "Vega" },
  { key: "extrinsic_value", label: "Extrinsic" },
  { key: "intrinsic_value", label: "Intrinsic" },
  { key: "source", label: "Freshness" },
];

// Secondary greeks hidden unless "Show greeks" is toggled on (keeps the default
// view compact; IV / Delta / Extrinsic / Intrinsic stay visible).
const GREEK_KEYS: (keyof Position)[] = ["gamma", "theta", "vega"];

// Column provenance, so the table can visually band live (TWS overlay) columns
// apart from settled (FlexQuery snapshot) columns. Identity/contract columns are
// neutral and left untinted.
type ColumnGroup = "live" | "flex" | "neutral";

const LIVE_KEYS = new Set<keyof Position>([
  "mark",
  "live_unrealized",
  "iv",
  "delta",
  "gamma",
  "theta",
  "vega",
  "extrinsic_value",
  "intrinsic_value",
  "source",
]);

// Live overlay *value* columns (excludes the "source"/Freshness badge column,
// which renders its own stale state). Blanked when the row's live overlay is
// stale so old TWS marks/greeks aren't shown as if current.
const LIVE_OVERLAY_VALUE_KEYS = new Set<keyof Position>([
  "mark",
  "live_unrealized",
  "iv",
  "delta",
  "gamma",
  "theta",
  "vega",
  "extrinsic_value",
  "intrinsic_value",
]);

// A row's live overlay is usable only when it's live-sourced AND not stale.
function isLiveFresh(pos: Position): boolean {
  return pos.source === "live" && !pos.live_is_stale;
}

const FLEX_KEYS = new Set<keyof Position>([
  "mark_price",
  "position_value",
  "fifo_pnl_unrealized",
]);

function columnGroup(key: keyof Position): ColumnGroup {
  if (LIVE_KEYS.has(key)) return "live";
  if (FLEX_KEYS.has(key)) return "flex";
  return "neutral";
}

// Tints per band. Body cells use group-hover so the row highlight still reads
// through the column tint. Neutral columns fall back to the row/thead defaults.
const HEADER_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-100",
  flex: "bg-amber-100",
  neutral: "",
};
const FILTER_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-50",
  flex: "bg-amber-50",
  neutral: "",
};
const CELL_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-50 group-hover:bg-sky-100",
  flex: "bg-amber-50 group-hover:bg-amber-100",
  neutral: "",
};

function regexMatch(
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

export default function PositionsTable() {
  const { privacyMode } = usePrivacy();
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [liveSyncing, setLiveSyncing] = useState(false);
  const [metricsSyncing, setMetricsSyncing] = useState(false);
  const [showGreeks, setShowGreeks] = useState(false);
  const [assignError, setAssignError] = useState<string | null>(null);
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [localSymbolFilter, setLocalSymbolFilter] = useState("");
  const [secTypeFilter, setSecTypeFilter] = useState("");
  const [dteMinFilter, setDteMinFilter] = useState("");
  const [dteMaxFilter, setDteMaxFilter] = useState("");
  const [sortColumn, setSortColumn] = useState<SortColumn | null>("symbol");
  const [sortDirection, setSortDirection] = useState<SortDirection>("asc");

  const dteMin = useMemo(() => {
    if (!dteMinFilter.trim()) return null;
    const parsed = Number(dteMinFilter);
    return Number.isFinite(parsed) ? parsed : null;
  }, [dteMinFilter]);

  const dteMax = useMemo(() => {
    if (!dteMaxFilter.trim()) return null;
    const parsed = Number(dteMaxFilter);
    return Number.isFinite(parsed) ? parsed : null;
  }, [dteMaxFilter]);

  // Hide the secondary greeks (gamma/theta/vega) unless the toggle is on.
  const columns = useMemo(
    () => COLUMNS.filter((c) => showGreeks || !GREEK_KEYS.includes(c.key)),
    [showGreeks],
  );

  const accountAliases = useMemo(() => {
    const seen = new Set<string>();
    for (const p of positions) seen.add(p.account_alias);
    return Array.from(seen).sort();
  }, [positions]);

  const sortedPositions = useMemo(() => {
    const filtered = positions.filter((p) => {
      const dteMatches =
        dteMin === null && dteMax === null
          ? true
          : p.dte !== null &&
            (dteMin === null || p.dte >= dteMin) &&
            (dteMax === null || p.dte <= dteMax);
      return (
        (accountFilter === "all" || p.account_alias === accountFilter) &&
        regexMatch(p.symbol, symbolFilter) &&
        regexMatch(p.local_symbol, localSymbolFilter) &&
        regexMatch(p.sec_type, secTypeFilter) &&
        dteMatches
      );
    });

    const expirySortValue = (p: Position): number | null => {
      const raw = (p.option_expiry_date ?? p.last_trade_date ?? "").trim();
      if (!raw) return null;
      const digits = raw.includes("-") ? raw.replaceAll("-", "") : raw;
      return /^\d{8}$/.test(digits) ? Number(digits) : null;
    };

    const sortValueFor = (
      p: Position,
      column: SortColumn,
    ): string | number | null => {
      if (column === "symbol") return p.symbol ? p.symbol.toUpperCase() : null;
      if (column === "local_symbol")
        return p.local_symbol ? p.local_symbol.toUpperCase() : null;
      if (column === "option_expiry_date") return expirySortValue(p);
      return p.dte;
    };

    const compareValues = (
      left: string | number | null,
      right: string | number | null,
      direction: SortDirection,
    ): number => {
      const leftNull = left === null;
      const rightNull = right === null;
      if (leftNull && rightNull) return 0;
      if (leftNull) return 1;
      if (rightNull) return -1;

      let cmp = 0;
      if (typeof left === "number" && typeof right === "number") {
        cmp = left - right;
      } else {
        cmp = String(left).localeCompare(String(right), undefined, {
          sensitivity: "base",
        });
      }
      return direction === "desc" ? -cmp : cmp;
    };

    if (sortColumn !== null && sortDirection !== "none") {
      filtered.sort((a, b) => {
        const sortDiff = compareValues(
          sortValueFor(a, sortColumn),
          sortValueFor(b, sortColumn),
          sortDirection,
        );
        if (sortDiff !== 0) return sortDiff;
        return a.con_id - b.con_id;
      });
    }

    return filtered;
  }, [
    positions,
    accountFilter,
    symbolFilter,
    localSymbolFilter,
    secTypeFilter,
    dteMin,
    dteMax,
    sortColumn,
    sortDirection,
  ]);

  const totalUnrealizedPnl = useMemo(() => {
    let total = 0;
    let any = false;
    for (const p of sortedPositions) {
      if (p.fifo_pnl_unrealized != null) {
        total += p.fifo_pnl_unrealized;
        any = true;
      }
    }
    return any ? total : null;
  }, [sortedPositions]);

  const totalLiveUnrealized = useMemo(() => {
    let total = 0;
    let any = false;
    for (const p of sortedPositions) {
      const val = isLiveFresh(p) ? p.live_unrealized : p.fifo_pnl_unrealized;
      if (val != null) {
        total += val;
        any = true;
      }
    }
    return any ? total : null;
  }, [sortedPositions]);

  // Aggregate cost basis (entry cost) for privacy-mode relative returns.
  // basis = current value − unrealized gain, so no dollar figure is exposed —
  // only the ratio total_pnl / total_basis is shown.
  const totalCostBasis = useMemo(() => {
    let total = 0;
    let any = false;
    for (const p of sortedPositions) {
      if (p.position_value != null && p.fifo_pnl_unrealized != null) {
        total += p.position_value - p.fifo_pnl_unrealized;
        any = true;
      }
    }
    return any ? total : null;
  }, [sortedPositions]);

  const newestMarkTs = useMemo(() => {
    let newest: string | null = null;
    for (const p of sortedPositions) {
      if (
        isLiveFresh(p) &&
        p.mark_ts &&
        (newest == null || p.mark_ts > newest)
      ) {
        newest = p.mark_ts;
      }
    }
    return newest;
  }, [sortedPositions]);

  const loadPositions = () => {
    fetch(`${API_BASE_URL}/positions`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setPositions)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadPositions();
  }, []);

  useSSE<Record<string, unknown>>("positions", () => {
    loadPositions();
  });

  const assignToTradeGroup = async (pos: Position, groupId: number) => {
    setAssignError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/trade-groups/${groupId}/positions:assign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            positions: [{ account_id: pos.account_id, con_id: pos.con_id }],
            source: "manual",
            created_by: "positions-ui",
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      loadPositions();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "Assign failed");
    }
  };

  const unassignFromTradeGroup = async (pos: Position, groupId: number) => {
    setAssignError(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/trade-groups/${groupId}/positions:unassign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            positions: [{ account_id: pos.account_id, con_id: pos.con_id }],
            source: "manual",
            created_by: "positions-ui",
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      loadPositions();
    } catch (err) {
      setAssignError(err instanceof Error ? err.message : "Unassign failed");
    }
  };

  const kickOffPositionSync = async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/positions/sync/flex-query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text:
            "Kick off flex query positions sync from Positions page.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(
        `Queued positions sync job #${data.job_id} (${data.status}).`,
      );
      window.setTimeout(() => loadPositions(), 1000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setSyncing(false);
    }
  };

  const kickOffIntradaySync = async () => {
    setLiveSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/positions/sync/intraday-tws`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Refresh live intraday overlay from Positions page.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      // The TWS session + reqTickers take longer than a flex enqueue; poll a few times.
      window.setTimeout(() => loadPositions(), 3000);
      window.setTimeout(() => loadPositions(), 8000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setLiveSyncing(false);
    }
  };

  const kickOffMetricsSync = async () => {
    setMetricsSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const res = await fetch(
        `${API_BASE_URL}/positions/sync/option-metrics-tws`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source: "manual-ui",
            request_text: "Refresh live option metrics from Positions page.",
            max_attempts: 3,
          }),
        },
      );
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(
        `Queued option-metrics TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      // The TWS session + reqTickers take longer than a flex enqueue; poll a few times.
      window.setTimeout(() => loadPositions(), 3000);
      window.setTimeout(() => loadPositions(), 8000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setMetricsSyncing(false);
    }
  };

  if (loading) return <p className="text-gray-500">Loading positions...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (positions.length === 0)
    return <p className="text-gray-500">No positions found.</p>;

  const clearFilters = () => {
    setSymbolFilter("");
    setLocalSymbolFilter("");
    setSecTypeFilter("");
    setDteMinFilter("");
    setDteMaxFilter("");
  };

  const isSortedBy = (column: SortColumn): boolean =>
    sortColumn === column && sortDirection !== "none";

  const sortIndicatorFor = (column: SortColumn): string => {
    if (sortColumn !== column || sortDirection === "none") return "↕";
    if (sortDirection === "asc") return "↑";
    return "↓";
  };

  const SORTABLE_KEYS: SortColumn[] = [
    "symbol",
    "local_symbol",
    "option_expiry_date",
    "dte",
  ];

  const ariaSortFor = (
    column: keyof Position,
  ): "ascending" | "descending" | "none" | undefined => {
    if (!SORTABLE_KEYS.includes(column as SortColumn)) return undefined;
    if (!isSortedBy(column as SortColumn)) return "none";
    return sortDirection === "asc" ? "ascending" : "descending";
  };

  const toggleSort = (column: SortColumn) => {
    if (sortColumn !== column) {
      setSortColumn(column);
      setSortDirection("none");
      return;
    }
    setSortDirection((prev) => {
      if (prev === "none") return "asc";
      if (prev === "asc") return "desc";
      setSortColumn(null);
      return "none";
    });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-900">Positions</h2>
          <button
            type="button"
            onClick={clearFilters}
            className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-700 hover:bg-gray-50"
          >
            Clear Filters
          </button>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-600">
            Unrealized PnL:{" "}
            <span
              className={
                totalUnrealizedPnl == null
                  ? "text-gray-500"
                  : totalUnrealizedPnl >= 0
                    ? "font-semibold text-emerald-700"
                    : "font-semibold text-red-700"
              }
            >
              {privacyMode
                ? formatRelativeReturn(totalUnrealizedPnl, totalCostBasis)
                : totalUnrealizedPnl == null
                  ? "—"
                  : totalUnrealizedPnl.toLocaleString(undefined, {
                      style: "currency",
                      currency: "USD",
                    })}
            </span>
          </span>
          <span className="text-sm text-gray-600">
            Live PnL:{" "}
            <span
              className={
                totalLiveUnrealized == null
                  ? "text-gray-500"
                  : totalLiveUnrealized >= 0
                    ? "font-semibold text-emerald-700"
                    : "font-semibold text-red-700"
              }
            >
              {privacyMode
                ? formatRelativeReturn(totalLiveUnrealized, totalCostBasis)
                : totalLiveUnrealized == null
                  ? "—"
                  : totalLiveUnrealized.toLocaleString(undefined, {
                      style: "currency",
                      currency: "USD",
                    })}
            </span>
            {newestMarkTs && (
              <span className="ml-1 text-xs text-gray-400">
                (live as of {formatMarkTime(newestMarkTs)})
              </span>
            )}
          </span>
          <button
            onClick={() => {
              void kickOffPositionSync();
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Kick Off Position Sync"}
          </button>
          <button
            onClick={() => {
              void kickOffIntradaySync();
            }}
            disabled={liveSyncing}
            className="rounded border border-emerald-300 px-3 py-1 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
          >
            {liveSyncing ? "Queueing..." : "Refresh Live (TWS)"}
          </button>
          <button
            onClick={() => {
              void kickOffMetricsSync();
            }}
            disabled={metricsSyncing}
            className="rounded border border-violet-300 px-3 py-1 text-sm text-violet-700 hover:bg-violet-50 disabled:opacity-50"
          >
            {metricsSyncing ? "Queueing..." : "Refresh Metrics (TWS)"}
          </button>
          <button
            type="button"
            onClick={() => setShowGreeks((v) => !v)}
            aria-pressed={showGreeks}
            className={`rounded border px-3 py-1 text-sm ${
              showGreeks
                ? "border-violet-400 bg-violet-50 text-violet-700"
                : "border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
          >
            {showGreeks ? "Hide greeks" : "Show greeks"}
          </button>
        </div>
      </div>

      {accountAliases.length > 1 && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAccountFilter("all")}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              accountFilter === "all"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All
          </button>
          {accountAliases.map((alias) => (
            <button
              key={alias}
              onClick={() => setAccountFilter(alias)}
              className={`rounded px-2.5 py-1 text-xs font-medium tracking-wide ${
                accountFilter === alias
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {alias}
            </button>
          ))}
        </div>
      )}

      {syncMessage && <p className="text-sm text-green-700">{syncMessage}</p>}
      {syncError && (
        <p className="text-sm text-red-600">Sync error: {syncError}</p>
      )}
      {assignError && (
        <p className="text-sm text-red-600">
          Trade group assignment error: {assignError}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              {columns.map((col) => (
                <th
                  key={col.key}
                  aria-sort={ariaSortFor(col.key)}
                  className={`px-3 py-2 font-semibold text-gray-700 whitespace-nowrap ${HEADER_TINT[columnGroup(col.key)]}`}
                >
                  {col.key === "symbol" ||
                  col.key === "local_symbol" ||
                  col.key === "option_expiry_date" ||
                  col.key === "dte" ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(col.key as SortColumn)}
                      className="inline-flex items-center gap-1 text-gray-700 hover:text-gray-900"
                      title={`Cycle ${col.label} sort`}
                    >
                      <span>{col.label}</span>
                      <span
                        aria-hidden="true"
                        className={
                          isSortedBy(col.key as SortColumn)
                            ? "text-gray-900"
                            : "text-gray-400"
                        }
                      >
                        {sortIndicatorFor(col.key as SortColumn)}
                      </span>
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              ))}
            </tr>
            <tr className="bg-gray-50 text-left">
              {columns.map((col) => (
                <th
                  key={`filter-${col.key}`}
                  className={`px-3 py-1 font-normal text-gray-700 whitespace-nowrap ${FILTER_TINT[columnGroup(col.key)]}`}
                >
                  {col.key === "symbol" ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        placeholder="Regex filter"
                        value={symbolFilter}
                        onChange={(e) => setSymbolFilter(e.target.value)}
                        className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                      />
                      {symbolFilter ? (
                        <button
                          type="button"
                          onClick={() => setSymbolFilter("")}
                          className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
                          title="Clear symbol filter"
                          aria-label="Clear symbol filter"
                        >
                          ×
                        </button>
                      ) : null}
                    </div>
                  ) : col.key === "local_symbol" ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        placeholder="Regex filter"
                        value={localSymbolFilter}
                        onChange={(e) => setLocalSymbolFilter(e.target.value)}
                        className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                      />
                      {localSymbolFilter ? (
                        <button
                          type="button"
                          onClick={() => setLocalSymbolFilter("")}
                          className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
                          title="Clear local symbol filter"
                          aria-label="Clear local symbol filter"
                        >
                          ×
                        </button>
                      ) : null}
                    </div>
                  ) : col.key === "sec_type" ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="text"
                        placeholder="Regex filter"
                        value={secTypeFilter}
                        onChange={(e) => setSecTypeFilter(e.target.value)}
                        className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                      />
                      {secTypeFilter ? (
                        <button
                          type="button"
                          onClick={() => setSecTypeFilter("")}
                          className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
                          title="Clear sec type filter"
                          aria-label="Clear sec type filter"
                        >
                          ×
                        </button>
                      ) : null}
                    </div>
                  ) : col.key === "dte" ? (
                    <div className="flex items-center gap-1">
                      <input
                        type="number"
                        placeholder="min"
                        value={dteMinFilter}
                        onChange={(e) => setDteMinFilter(e.target.value)}
                        className="w-14 rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-700"
                      />
                      <input
                        type="number"
                        placeholder="max"
                        value={dteMaxFilter}
                        onChange={(e) => setDteMaxFilter(e.target.value)}
                        className="w-14 rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-700"
                      />
                      {dteMinFilter || dteMaxFilter ? (
                        <button
                          type="button"
                          onClick={() => {
                            setDteMinFilter("");
                            setDteMaxFilter("");
                          }}
                          className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
                          title="Clear DTE filters"
                          aria-label="Clear DTE filters"
                        >
                          ×
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedPositions.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No positions match the current filters.
                </td>
              </tr>
            )}
            {sortedPositions.map((pos) => (
              <tr
                key={pos.id}
                className="group border-b border-gray-200 hover:bg-gray-50"
              >
                {columns.map((col) => {
                  const renderNumeric = (val: number | null): React.ReactNode =>
                    formatMoney(val);
                  let content: React.ReactNode;
                  let extraClass = "";
                  if (
                    pos.live_is_stale &&
                    LIVE_OVERLAY_VALUE_KEYS.has(col.key)
                  ) {
                    // Stale live overlay: blank the value so old TWS marks/greeks
                    // aren't presented as current. The Freshness badge (source
                    // column) still renders and flags the row as stale.
                    content = "—";
                  } else if (col.key === "trade_groups") {
                    content = (
                      <span className="inline-flex items-center gap-1 whitespace-nowrap">
                        {pos.trade_groups.map((group) => (
                          <span
                            key={group.id}
                            className="inline-flex items-center gap-0.5 rounded bg-gray-100 px-1.5 py-0.5"
                          >
                            <Link
                              to={`/strategies?trade_group_id=${group.id}`}
                              className="text-blue-600 hover:underline"
                            >
                              {group.name}
                            </Link>
                            <button
                              type="button"
                              onClick={() => {
                                if (
                                  window.confirm(
                                    `Remove all fills of this position from "${group.name}"?`,
                                  )
                                )
                                  unassignFromTradeGroup(pos, group.id);
                              }}
                              className="text-gray-400 hover:text-red-600"
                              title="Remove position's fills from this trade group"
                              aria-label={`Remove from ${group.name}`}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                        <TradeGroupSearchSelect
                          accountId={pos.account_id}
                          contractDisplayName={pos.contract_display_name}
                          onSelect={(group) =>
                            assignToTradeGroup(pos, group.id)
                          }
                          renderTrigger={(open) => (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                open();
                              }}
                              className="rounded border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-400 hover:border-blue-300 hover:text-blue-600"
                              title="Assign to trade group"
                              aria-label="Assign to trade group"
                            >
                              {pos.trade_groups.length === 0 ? "+ Assign" : "+"}
                            </button>
                          )}
                        />
                      </span>
                    );
                  } else if (col.key === "position" && privacyMode) {
                    content = PRIVACY_MASK;
                  } else if (col.key === "last_trade_date") {
                    content = formatExpiry(pos[col.key] as string | null);
                  } else if (col.key === "option_expiry_date") {
                    content = expiryForPosition(pos);
                  } else if (col.key === "strike" && pos.sec_type === "FUT") {
                    content = "—";
                  } else if (col.key === "strike") {
                    content = formatStrike(pos.strike);
                  } else if (col.key === "multiplier") {
                    content = formatMultiplier(pos.multiplier);
                  } else if (col.key === "avg_cost") {
                    content = privacyMode
                      ? PRIVACY_MASK
                      : formatMoney(pos.avg_cost);
                  } else if (col.key === "mark_price") {
                    content = privacyMode
                      ? PRIVACY_MASK
                      : renderNumeric(pos.mark_price);
                  } else if (col.key === "position_value") {
                    content = privacyMode
                      ? PRIVACY_MASK
                      : renderNumeric(pos.position_value);
                  } else if (col.key === "fifo_pnl_unrealized") {
                    if (pos.fifo_pnl_unrealized != null) {
                      extraClass =
                        pos.fifo_pnl_unrealized >= 0
                          ? "text-emerald-700 font-medium"
                          : "text-red-700 font-medium";
                    }
                    if (privacyMode) {
                      content = formatRelativeReturn(
                        pos.fifo_pnl_unrealized,
                        positionCostBasis(pos),
                      );
                    } else {
                      content = renderNumeric(pos.fifo_pnl_unrealized);
                    }
                  } else if (col.key === "mark") {
                    content = privacyMode
                      ? PRIVACY_MASK
                      : renderNumeric(pos.mark);
                  } else if (col.key === "live_unrealized") {
                    if (pos.live_unrealized != null) {
                      extraClass =
                        pos.live_unrealized >= 0
                          ? "text-emerald-700 font-medium"
                          : "text-red-700 font-medium";
                    }
                    if (privacyMode) {
                      content = formatRelativeReturn(
                        pos.live_unrealized,
                        positionCostBasis(pos),
                      );
                    } else {
                      content = renderNumeric(pos.live_unrealized);
                    }
                  } else if (col.key === "iv") {
                    // IV is a risk metric, not dollar exposure — show in privacy.
                    content = formatPercent(pos.iv);
                  } else if (col.key === "delta") {
                    content = formatDelta(pos.delta);
                  } else if (
                    col.key === "gamma" ||
                    col.key === "theta" ||
                    col.key === "vega"
                  ) {
                    content = formatGreek(pos[col.key] as number | null);
                  } else if (
                    col.key === "extrinsic_value" ||
                    col.key === "intrinsic_value"
                  ) {
                    // Per-unit prices — mask like the other price columns.
                    content = privacyMode
                      ? PRIVACY_MASK
                      : renderNumeric(pos[col.key] as number | null);
                  } else if (col.key === "source") {
                    if (pos.source === "live" && pos.live_is_stale) {
                      // Live snapshot predates the newer settled snapshot —
                      // flag as stale (amber) with the age of the live data, so
                      // it never reads as a current green "live" quote.
                      const staleTs = formatMarkTime(
                        pos.mark_ts ?? pos.live_fetched_at,
                      );
                      content = (
                        <span
                          className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800"
                          title="Live TWS overlay is older than the latest settled (FlexQuery) snapshot. Refresh Live (TWS) to update."
                        >
                          stale{staleTs ? ` ${staleTs}` : ""}
                        </span>
                      );
                    } else if (pos.source === "live") {
                      const ts = formatMarkTime(pos.mark_ts);
                      content = (
                        <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800">
                          live{ts ? ` ${ts}` : ""}
                        </span>
                      );
                    } else {
                      content = (
                        <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
                          settled
                        </span>
                      );
                    }
                  } else if (col.key === "contract_display_name") {
                    // Informational only — no link.
                    content = pos.contract_display_name;
                  } else if (col.key === "con_id") {
                    content = pos.con_id ? (
                      <Link
                        to={`/trades?con_id=${pos.con_id}`}
                        className="font-mono text-blue-600 hover:underline"
                        title="Search all trades for this Contract ID (all time, all accounts)"
                      >
                        {pos.con_id}
                      </Link>
                    ) : (
                      "—"
                    );
                  } else {
                    content = pos[col.key] ?? "—";
                  }
                  return (
                    <td
                      key={col.key}
                      className={`px-3 py-2 whitespace-nowrap ${CELL_TINT[columnGroup(col.key)]} ${extraClass}`}
                    >
                      {content}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
