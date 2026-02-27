import { Fragment, useEffect, useState } from "react";

interface Leg {
  id: number;
  con_id: number;
  ratio: number | null;
  position: number | null;
  avg_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
}

interface Spread {
  id: number;
  account_id: number;
  account_alias: string;
  source: string;
  combo_key: string;
  name: string | null;
  description: string | null;
  position: number | null;
  avg_price: number | null;
  market_value: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  fetched_at: string;
  legs: Leg[];
}

interface UnmatchedLeg {
  id: number;
  account_alias: string;
  con_id: number;
  symbol: string | null;
  local_symbol: string | null;
  sec_type: string | null;
  last_trade_date: string | null;
  position: number;
  avg_cost: number;
  fetched_at: string;
}

function formatPnl(value: number | null): string {
  if (value === null || value === undefined) return "\u2014";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}`;
}

function pnlColorClass(value: number | null): string {
  if (value === null || value === undefined) return "text-gray-500";
  if (value > 0) return "text-green-700";
  if (value < 0) return "text-red-600";
  return "text-gray-700";
}

function formatPrice(value: number | null): string {
  if (value === null || value === undefined) return "\u2014";
  return value.toFixed(2);
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

export default function SpreadsTable() {
  const [spreads, setSpreads] = useState<Spread[]>([]);
  const [unmatchedLegs, setUnmatchedLegs] = useState<UnmatchedLeg[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [tab, setTab] = useState<"combos" | "unmatched">("combos");

  const loadData = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      fetch("http://localhost:8000/api/v1/spreads").then((r) => {
        if (!r.ok) throw new Error(`Spreads: HTTP ${r.status}`);
        return r.json();
      }),
      fetch(
        "http://localhost:8000/api/v1/spreads/unmatched-legs?symbol=CL",
      ).then((r) => {
        if (!r.ok) throw new Error(`Unmatched legs: HTTP ${r.status}`);
        return r.json();
      }),
    ])
      .then(([spreadsData, unmatchedData]) => {
        setSpreads(spreadsData);
        setUnmatchedLegs(unmatchedData);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, []);

  const toggleExpand = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const kickOffSync = async () => {
    setSyncing(true);
    setSyncError(null);
    setSyncMessage(null);
    try {
      const res = await fetch("http://localhost:8000/api/v1/spreads/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Kick off combo positions sync from Spreads page.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(`Queued combo sync job #${data.job_id} (${data.status}).`);
      window.setTimeout(() => loadData(), 2000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setSyncing(false);
    }
  };

  if (loading) return <p className="text-gray-500">Loading spreads...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Spreads</h2>
        <button
          onClick={() => {
            void kickOffSync();
          }}
          disabled={syncing}
          className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
        >
          {syncing ? "Queueing..." : "Sync Combo Positions"}
        </button>
      </div>

      {syncMessage && <p className="text-sm text-green-700">{syncMessage}</p>}
      {syncError && (
        <p className="text-sm text-red-600">Sync error: {syncError}</p>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200">
        <button
          onClick={() => setTab("combos")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === "combos"
              ? "border-blue-500 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Native Combos
          <span className="ml-1.5 text-xs text-gray-400">
            ({spreads.length})
          </span>
        </button>
        <button
          onClick={() => setTab("unmatched")}
          className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
            tab === "unmatched"
              ? "border-blue-500 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Unmatched CL Legs
          <span className="ml-1.5 text-xs text-gray-400">
            ({unmatchedLegs.length})
          </span>
        </button>
      </div>

      {/* Combos tab */}
      {tab === "combos" && (
        <div className="overflow-x-auto">
          {spreads.length === 0 ? (
            <p className="text-gray-500 py-4">
              No combo positions found. Run a sync to fetch from CPAPI.
            </p>
          ) : (
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="bg-gray-100 text-left">
                  <th className="px-3 py-2 font-semibold text-gray-700 w-8" />
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Account
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Name / Description
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                    Position
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Legs
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                    Avg Price
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                    Unrealized PnL
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Last Synced
                  </th>
                </tr>
              </thead>
              <tbody>
                {spreads.map((spread) => {
                  const expanded = expandedIds.has(spread.id);
                  const legsSummary = spread.legs
                    .map(
                      (l) =>
                        `${l.ratio != null && l.ratio < 0 ? "" : "+"}${l.ratio ?? "?"} conid:${l.con_id}`,
                    )
                    .join(" / ");
                  return (
                    <Fragment key={spread.id}>
                      <tr
                        className="border-b border-gray-200 hover:bg-gray-50 cursor-pointer"
                        onClick={() => toggleExpand(spread.id)}
                      >
                        <td className="px-3 py-2 text-gray-400">
                          {expanded ? "\u25BE" : "\u25B8"}
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {spread.account_alias}
                        </td>
                        <td className="px-3 py-2">
                          <div>{spread.name || "\u2014"}</div>
                          {spread.description && (
                            <div className="text-xs text-gray-500">
                              {spread.description}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {spread.position ?? "\u2014"}
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-600 whitespace-nowrap">
                          {legsSummary || "\u2014"}
                        </td>
                        <td className="px-3 py-2 text-right whitespace-nowrap">
                          {formatPrice(spread.avg_price)}
                        </td>
                        <td
                          className={`px-3 py-2 text-right whitespace-nowrap ${pnlColorClass(spread.unrealized_pnl)}`}
                        >
                          {formatPnl(spread.unrealized_pnl)}
                        </td>
                        <td className="px-3 py-2 text-xs text-gray-500 whitespace-nowrap">
                          {formatTimestamp(spread.fetched_at)}
                        </td>
                      </tr>
                      {expanded && spread.legs.length > 0 && (
                        <tr>
                          <td colSpan={8} className="px-6 py-2 bg-gray-50">
                            <table className="min-w-full text-xs">
                              <thead>
                                <tr className="text-left text-gray-500">
                                  <th className="px-2 py-1">Con ID</th>
                                  <th className="px-2 py-1 text-right">
                                    Ratio
                                  </th>
                                  <th className="px-2 py-1 text-right">
                                    Position
                                  </th>
                                  <th className="px-2 py-1 text-right">
                                    Avg Price
                                  </th>
                                  <th className="px-2 py-1 text-right">
                                    Market Value
                                  </th>
                                  <th className="px-2 py-1 text-right">
                                    Unrealized PnL
                                  </th>
                                  <th className="px-2 py-1 text-right">
                                    Realized PnL
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {spread.legs.map((leg) => (
                                  <tr
                                    key={leg.id}
                                    className="border-t border-gray-200"
                                  >
                                    <td className="px-2 py-1">{leg.con_id}</td>
                                    <td className="px-2 py-1 text-right">
                                      {leg.ratio ?? "\u2014"}
                                    </td>
                                    <td className="px-2 py-1 text-right">
                                      {leg.position ?? "\u2014"}
                                    </td>
                                    <td className="px-2 py-1 text-right">
                                      {formatPrice(leg.avg_price)}
                                    </td>
                                    <td className="px-2 py-1 text-right">
                                      {formatPrice(leg.market_value)}
                                    </td>
                                    <td
                                      className={`px-2 py-1 text-right ${pnlColorClass(leg.unrealized_pnl)}`}
                                    >
                                      {formatPnl(leg.unrealized_pnl)}
                                    </td>
                                    <td
                                      className={`px-2 py-1 text-right ${pnlColorClass(leg.realized_pnl)}`}
                                    >
                                      {formatPnl(leg.realized_pnl)}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Unmatched legs tab */}
      {tab === "unmatched" && (
        <div className="overflow-x-auto">
          {unmatchedLegs.length === 0 ? (
            <p className="text-gray-500 py-4">No unmatched CL legs found.</p>
          ) : (
            <table className="min-w-full border-collapse text-sm">
              <thead>
                <tr className="bg-gray-100 text-left">
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Account
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Con ID
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Symbol
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Local Symbol
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Sec Type
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Last Trade Date
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                    Position
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700 text-right">
                    Avg Cost
                  </th>
                  <th className="px-3 py-2 font-semibold text-gray-700">
                    Fetched At
                  </th>
                </tr>
              </thead>
              <tbody>
                {unmatchedLegs.map((leg) => (
                  <tr
                    key={leg.id}
                    className="border-b border-gray-200 hover:bg-gray-50"
                  >
                    <td className="px-3 py-2 whitespace-nowrap">
                      {leg.account_alias}
                    </td>
                    <td className="px-3 py-2">{leg.con_id}</td>
                    <td className="px-3 py-2">{leg.symbol ?? "\u2014"}</td>
                    <td className="px-3 py-2">
                      {leg.local_symbol ?? "\u2014"}
                    </td>
                    <td className="px-3 py-2">{leg.sec_type ?? "\u2014"}</td>
                    <td className="px-3 py-2">
                      {leg.last_trade_date ?? "\u2014"}
                    </td>
                    <td className="px-3 py-2 text-right">{leg.position}</td>
                    <td className="px-3 py-2 text-right">
                      {formatPrice(leg.avg_cost)}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">
                      {formatTimestamp(leg.fetched_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
