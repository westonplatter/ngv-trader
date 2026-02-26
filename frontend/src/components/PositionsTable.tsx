import { Fragment, useEffect, useMemo, useState } from "react";

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
  fetched_at: string;
}

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
  { key: "con_id", label: "Con ID" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "currency", label: "Currency" },
  { key: "contract_display_name", label: "Contract" },
  { key: "local_symbol", label: "Local Symbol" },
  { key: "trading_class", label: "Trading Class" },
  { key: "last_trade_date", label: "Last Trade Date" },
  { key: "option_expiry_date", label: "Expiry" },
  { key: "dte", label: "DTE" },
  { key: "strike", label: "Strike" },
  { key: "right", label: "Call/Put" },
  { key: "multiplier", label: "Multiplier" },
  { key: "position", label: "Position" },
  { key: "avg_cost", label: "Avg Cost" },
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
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [collapsedAccounts, setCollapsedAccounts] = useState<Set<string>>(
    new Set(),
  );
  const [symbolFilter, setSymbolFilter] = useState("");
  const [localSymbolFilter, setLocalSymbolFilter] = useState("");
  const [secTypeFilter, setSecTypeFilter] = useState("");
  const [dteMinFilter, setDteMinFilter] = useState("");
  const [dteMaxFilter, setDteMaxFilter] = useState("");
  const [dteSortDirection, setDteSortDirection] = useState<
    "none" | "desc" | "asc"
  >("none");

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

  const groupedPositions = useMemo(() => {
    const filtered = positions.filter((p) => {
      const dteMatches =
        dteMin === null && dteMax === null
          ? true
          : p.dte !== null &&
            (dteMin === null || p.dte >= dteMin) &&
            (dteMax === null || p.dte <= dteMax);
      return (
        regexMatch(p.symbol, symbolFilter) &&
        regexMatch(p.local_symbol, localSymbolFilter) &&
        regexMatch(p.sec_type, secTypeFilter) &&
        dteMatches
      );
    });

    const dteSortValue = (p: Position): number =>
      p.dte === null ? Number.NEGATIVE_INFINITY : p.dte;

    const groups = new Map<string, Position[]>();
    for (const pos of filtered) {
      const key = pos.account_alias;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(pos);
    }

    for (const rows of groups.values()) {
      if (dteSortDirection !== "none") {
        rows.sort((a, b) => {
          const dteDiff =
            dteSortDirection === "desc"
              ? dteSortValue(b) - dteSortValue(a)
              : dteSortValue(a) - dteSortValue(b);
          if (dteDiff !== 0) return dteDiff;
          return a.con_id - b.con_id;
        });
      }
    }

    if (dteSortDirection === "none") {
      return groups;
    }

    return new Map(
      [...groups.entries()].sort(([, rowsA], [, rowsB]) => {
        const topA =
          rowsA.length > 0 ? dteSortValue(rowsA[0]) : Number.NEGATIVE_INFINITY;
        const topB =
          rowsB.length > 0 ? dteSortValue(rowsB[0]) : Number.NEGATIVE_INFINITY;
        return dteSortDirection === "desc" ? topB - topA : topA - topB;
      }),
    );
  }, [
    positions,
    symbolFilter,
    localSymbolFilter,
    secTypeFilter,
    dteMin,
    dteMax,
    dteSortDirection,
  ]);

  const toggleAccount = (alias: string) => {
    setCollapsedAccounts((prev) => {
      const next = new Set(prev);
      if (next.has(alias)) next.delete(alias);
      else next.add(alias);
      return next;
    });
  };

  const loadPositions = () => {
    fetch("http://localhost:8000/api/v1/positions")
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

  const kickOffPositionSync = async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const res = await fetch("http://localhost:8000/api/v1/positions/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Kick off positions sync from Positions page.",
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

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Positions</h2>
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
                  className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap"
                >
                  {col.key === "dte" ? (
                    <button
                      type="button"
                      onClick={() => {
                        setDteSortDirection((prev) => {
                          if (prev === "none") return "desc";
                          if (prev === "desc") return "asc";
                          return "none";
                        });
                      }}
                      className="inline-flex items-center gap-1 text-gray-700 hover:text-gray-900"
                      title="Cycle DTE sort: None, Desc, Asc"
                    >
                      {col.label}:{" "}
                      {dteSortDirection === "none"
                        ? "None"
                        : dteSortDirection === "desc"
                          ? "Desc"
                          : "Asc"}
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
                    <input
                      type="text"
                      placeholder="Regex filter"
                      value={symbolFilter}
                      onChange={(e) => setSymbolFilter(e.target.value)}
                      className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                    />
                  ) : col.key === "local_symbol" ? (
                    <input
                      type="text"
                      placeholder="Regex filter"
                      value={localSymbolFilter}
                      onChange={(e) => setLocalSymbolFilter(e.target.value)}
                      className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                    />
                  ) : col.key === "sec_type" ? (
                    <input
                      type="text"
                      placeholder="Regex filter"
                      value={secTypeFilter}
                      onChange={(e) => setSecTypeFilter(e.target.value)}
                      className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
                    />
                  ) : col.key === "dte" ? (
                    <div className="flex gap-1">
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
                    </div>
                  ) : null}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...groupedPositions.entries()].map(([account, rows]) => {
              const collapsed = collapsedAccounts.has(account);
              return (
                <Fragment key={account}>
                  <tr
                    className="bg-gray-100 cursor-pointer select-none"
                    onClick={() => toggleAccount(account)}
                  >
                    <td
                      colSpan={COLUMNS.length}
                      className="px-3 py-2 font-semibold text-gray-800"
                    >
                      <span className="mr-2">{collapsed ? "▸" : "▾"}</span>
                      {account}
                      <span className="ml-2 text-xs font-normal text-gray-500">
                        ({rows.length} position{rows.length !== 1 ? "s" : ""})
                      </span>
                    </td>
                  </tr>
                  {!collapsed &&
                    rows.map((pos) => (
                      <tr
                        key={pos.id}
                        className="border-b border-gray-200 hover:bg-gray-50"
                      >
                        {COLUMNS.map((col) => (
                          <td
                            key={col.key}
                            className="px-3 py-2 whitespace-nowrap"
                          >
                            {col.key === "last_trade_date"
                              ? formatExpiry(pos[col.key] as string | null)
                              : col.key === "option_expiry_date"
                                ? expiryForPosition(pos)
                                : col.key === "strike" && pos.sec_type === "FUT"
                                  ? "—"
                                  : (pos[col.key] ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
