import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";
import { API_BASE_URL } from "../config";
import { useSSE } from "../lib/events";

interface Position {
  id: number;
  account_alias: string;
  contract_display_name: string;
  con_id: number;
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
}

type SortDirection = "none" | "desc" | "asc";
type SortColumn =
  | "symbol"
  | "local_symbol"
  | "option_expiry_date"
  | "dte";

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

const COLUMNS: { key: keyof Position; label: string }[] = [
  { key: "account_alias", label: "Account" },
  { key: "con_id", label: "Con ID" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "currency", label: "Currency" },
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
];

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
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [localSymbolFilter, setLocalSymbolFilter] = useState("");
  const [secTypeFilter, setSecTypeFilter] = useState("");
  const [dteMinFilter, setDteMinFilter] = useState("");
  const [dteMaxFilter, setDteMaxFilter] = useState("");
  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>("none");

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
                ? PRIVACY_MASK
                : totalUnrealizedPnl == null
                  ? "—"
                  : totalUnrealizedPnl.toLocaleString(undefined, {
                      style: "currency",
                      currency: "USD",
                    })}
            </span>
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

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  aria-sort={ariaSortFor(col.key)}
                  className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap"
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
              {COLUMNS.map((col) => (
                <th
                  key={`filter-${col.key}`}
                  className="px-3 py-1 font-normal text-gray-700 whitespace-nowrap"
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
                  colSpan={COLUMNS.length}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No positions match the current filters.
                </td>
              </tr>
            )}
            {sortedPositions.map((pos) => (
              <tr
                key={pos.id}
                className="border-b border-gray-200 hover:bg-gray-50"
              >
                {COLUMNS.map((col) => {
                  const renderNumeric = (
                    val: number | null,
                  ): React.ReactNode => (val == null ? "—" : val.toFixed(2));
                  let content: React.ReactNode;
                  let extraClass = "";
                  if (col.key === "position" && privacyMode) {
                    content = PRIVACY_MASK;
                  } else if (col.key === "last_trade_date") {
                    content = formatExpiry(pos[col.key] as string | null);
                  } else if (col.key === "option_expiry_date") {
                    content = expiryForPosition(pos);
                  } else if (col.key === "strike" && pos.sec_type === "FUT") {
                    content = "—";
                  } else if (col.key === "mark_price") {
                    content = renderNumeric(pos.mark_price);
                  } else if (col.key === "position_value") {
                    content = renderNumeric(pos.position_value);
                  } else if (col.key === "fifo_pnl_unrealized") {
                    if (privacyMode) {
                      content = PRIVACY_MASK;
                    } else {
                      content = renderNumeric(pos.fifo_pnl_unrealized);
                      if (pos.fifo_pnl_unrealized != null) {
                        extraClass =
                          pos.fifo_pnl_unrealized >= 0
                            ? "text-emerald-700 font-medium"
                            : "text-red-700 font-medium";
                      }
                    }
                  } else {
                    content = pos[col.key] ?? "—";
                  }
                  return (
                    <td
                      key={col.key}
                      className={`px-3 py-2 whitespace-nowrap ${extraClass}`}
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
