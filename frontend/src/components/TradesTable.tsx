import { useEffect, useMemo, useState } from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";

const API_BASE_URL = "http://localhost:8000/api/v1";

interface Trade {
  id: number;
  account_id: number;
  account_alias: string | null;
  ib_perm_id: number | null;
  order_ref: string | null;
  ib_order_id: number | null;
  symbol: string | null;
  sec_type: string | null;
  side: string | null;
  exchange: string | null;
  currency: string | null;
  status: string;
  total_quantity: number;
  avg_price: number | null;
  first_executed_at: string | null;
  last_executed_at: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
}

interface TradeExecution {
  id: number;
  trade_id: number;
  account_id: number;
  ib_exec_id: string;
  exec_id_base: string;
  exec_revision: number;
  ib_perm_id: number | null;
  ib_order_id: number | null;
  order_ref: string | null;
  sec_type: string | null;
  con_id: number | null;
  exec_role: string;
  executed_at: string;
  quantity: number;
  price: number;
  side: string | null;
  exchange: string | null;
  currency: string | null;
  liquidity: string | null;
  commission: number | null;
  is_canonical: boolean;
  contract_display: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
}

const STATUS_CLASS: Record<string, string> = {
  filled: "bg-emerald-100 text-emerald-800",
  partial: "bg-blue-100 text-blue-800",
  cancelled: "bg-zinc-200 text-zinc-800",
  unknown: "bg-gray-100 text-gray-800",
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "—";
  const d = new Date(parsed);
  return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function formatPrice(value: number | null | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

export default function TradesTable() {
  const { privacyMode } = usePrivacy();
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [timeRange, setTimeRange] = useState<string>("all");
  const [expandedTradeId, setExpandedTradeId] = useState<number | null>(null);
  const [executions, setExecutions] = useState<TradeExecution[]>([]);
  const [executionsLoading, setExecutionsLoading] = useState(false);

  const loadTrades = () => {
    fetch(`${API_BASE_URL}/trades`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: Trade[]) => {
        setTrades(data);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch(`${API_BASE_URL}/trades`)
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((data: Trade[]) => {
          if (!active) return;
          setTrades(data);
          setError(null);
        })
        .catch((err: Error) => {
          if (!active) return;
          setError(err.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    };

    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const symbolRegex = useMemo(() => {
    const raw = symbolFilter.trim();
    if (!raw) return null;
    try {
      return new RegExp(raw, "i");
    } catch {
      return null;
    }
  }, [symbolFilter]);

  const accounts = useMemo(() => {
    const seen = new Map<string, string>();
    for (const t of trades) {
      const key = String(t.account_id);
      if (!seen.has(key)) {
        seen.set(key, t.account_alias ?? `Account ${t.account_id}`);
      }
    }
    return Array.from(seen.entries()).map(([id, label]) => ({ id, label }));
  }, [trades]);

  const filteredTrades = useMemo(() => {
    let next = trades;
    if (accountFilter !== "all") {
      next = next.filter((t) => String(t.account_id) === accountFilter);
    }
    if (symbolRegex) {
      next = next.filter((t) => symbolRegex.test(t.symbol ?? ""));
    }
    if (timeRange !== "all") {
      const hoursMap: Record<string, number> = {
        "24h": 24,
        "3d": 72,
        "7d": 168,
      };
      const hours = hoursMap[timeRange];
      if (hours) {
        const cutoff = Date.now() - hours * 60 * 60 * 1000;
        next = next.filter((t) => {
          const ts = t.last_executed_at ?? t.first_executed_at;
          if (!ts) return false;
          return Date.parse(ts) >= cutoff;
        });
      }
    }
    return next;
  }, [trades, accountFilter, symbolRegex, timeRange]);

  const kickOffTradesSync = async (lookbackDays: number, label: string) => {
    setSyncing(true);
    setSyncMessage(null);
    setSyncError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/trades/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: `${label} from Trades page.`,
          max_attempts: 3,
          lookback_days: lookbackDays,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(
        `Queued ${label.toLowerCase()} job #${data.job_id} (${data.status}).`,
      );
      window.setTimeout(() => loadTrades(), 2000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setSyncing(false);
    }
  };

  const toggleExecutions = async (tradeId: number) => {
    if (expandedTradeId === tradeId) {
      setExpandedTradeId(null);
      setExecutions([]);
      return;
    }
    setExpandedTradeId(tradeId);
    setExecutionsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/trades/${tradeId}/executions`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: TradeExecution[] = await res.json();
      setExecutions(data);
    } catch {
      setExecutions([]);
    } finally {
      setExecutionsLoading(false);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Trades</h2>
          <p className="text-xs text-gray-500">{trades.length} trade(s)</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              void kickOffTradesSync(1, "Quick sync");
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Quick Sync (1d)"}
          </button>
          <button
            onClick={() => {
              void kickOffTradesSync(7, "Full sync");
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Full Sync (7d)"}
          </button>
        </div>
      </div>

      {accounts.length > 1 && (
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
          {accounts.map((acct) => (
            <button
              key={acct.id}
              onClick={() => setAccountFilter(acct.id)}
              className={`rounded px-2.5 py-1 text-xs font-medium tracking-wide ${
                accountFilter === acct.id
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {acct.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        {[
          { id: "all", label: "All" },
          { id: "24h", label: "24h" },
          { id: "3d", label: "3d" },
          { id: "7d", label: "7d" },
        ].map((opt) => (
          <button
            key={opt.id}
            onClick={() => setTimeRange(opt.id)}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              timeRange === opt.id
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {syncMessage && <p className="text-sm text-green-700">{syncMessage}</p>}
      {syncError && (
        <p className="text-sm text-red-600">Sync error: {syncError}</p>
      )}
      {loading && <p className="text-gray-500">Loading trades...</p>}
      {error && <p className="text-red-600">Error: {error}</p>}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap w-8" />
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Last Exec
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                <div className="space-y-1">
                  <input
                    value={symbolFilter}
                    onChange={(e) => setSymbolFilter(e.target.value)}
                    placeholder="Filter"
                    className="w-24 rounded border border-gray-300 px-2 py-0.5 text-xs font-normal text-gray-700"
                  />
                  <div>Symbol</div>
                </div>
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Type
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Side
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Qty
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Avg Price
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Account
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Status
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Perm ID
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Order Ref
              </th>
            </tr>
          </thead>
          <tbody>
            {!loading && filteredTrades.length === 0 && (
              <tr>
                <td
                  colSpan={11}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No trades found.
                </td>
              </tr>
            )}
            {filteredTrades.map((trade) => (
              <>
                <tr
                  key={trade.id}
                  onClick={() => {
                    void toggleExecutions(trade.id);
                  }}
                  className="border-b border-gray-200 hover:bg-gray-50 cursor-pointer"
                >
                  <td className="px-3 py-2 whitespace-nowrap text-gray-400 text-xs">
                    {expandedTradeId === trade.id ? "▼" : "▶"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    {formatDateTime(trade.last_executed_at)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-800 font-medium">
                    {(trade.symbol ?? "—").toUpperCase()}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    {trade.sec_type ?? "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    {trade.side ?? "—"}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    {privacyMode ? PRIVACY_MASK : trade.total_quantity}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    {formatPrice(trade.avg_price)}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                    {trade.account_alias ?? `Account ${trade.account_id}`}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[trade.status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {trade.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-600 text-xs">
                    {privacyMode ? PRIVACY_MASK : (trade.ib_perm_id ?? "—")}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-600 text-xs truncate max-w-[160px]">
                    {trade.order_ref ?? "—"}
                  </td>
                </tr>
                {expandedTradeId === trade.id && (
                  <tr key={`exec-${trade.id}`}>
                    <td colSpan={11} className="p-0">
                      <div className="bg-gray-50 px-6 py-3 border-b border-gray-200">
                        <h4 className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-2">
                          Executions
                        </h4>
                        {executionsLoading && (
                          <p className="text-xs text-gray-500">Loading...</p>
                        )}
                        {!executionsLoading && executions.length === 0 && (
                          <p className="text-xs text-gray-500">
                            No executions found.
                          </p>
                        )}
                        {!executionsLoading && executions.length > 0 && (
                          <table className="min-w-full border-collapse text-xs">
                            <thead>
                              <tr className="text-left text-gray-500">
                                <th className="px-2 py-1 font-medium">Time</th>
                                <th className="px-2 py-1 font-medium">
                                  Contract
                                </th>
                                <th className="px-2 py-1 font-medium">Role</th>
                                <th className="px-2 py-1 font-medium">Side</th>
                                <th className="px-2 py-1 font-medium">Qty</th>
                                <th className="px-2 py-1 font-medium">Price</th>
                                <th className="px-2 py-1 font-medium">
                                  Commission
                                </th>
                                <th className="px-2 py-1 font-medium">
                                  Exchange
                                </th>
                                <th className="px-2 py-1 font-medium">
                                  Exec ID
                                </th>
                                <th className="px-2 py-1 font-medium">Rev</th>
                                <th className="px-2 py-1 font-medium">
                                  Canonical
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {executions.map((ex) => (
                                <tr
                                  key={ex.id}
                                  className={`border-t border-gray-200 ${!ex.is_canonical ? "opacity-50" : ""}`}
                                >
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {formatDateTime(ex.executed_at)}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-800 font-medium">
                                    {ex.contract_display ?? "—"}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {ex.exec_role === "combo_summary"
                                      ? "COMBO"
                                      : ex.exec_role === "leg"
                                        ? "LEG"
                                        : "—"}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {ex.side ?? "—"}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {privacyMode ? PRIVACY_MASK : ex.quantity}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {formatPrice(ex.price)}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {formatPrice(ex.commission)}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-700">
                                    {ex.exchange ?? "—"}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-500 font-mono truncate max-w-[200px]">
                                    {privacyMode ? PRIVACY_MASK : ex.ib_exec_id}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap text-gray-600">
                                    .{String(ex.exec_revision).padStart(2, "0")}
                                  </td>
                                  <td className="px-2 py-1 whitespace-nowrap">
                                    {ex.is_canonical ? (
                                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-emerald-700 font-medium">
                                        yes
                                      </span>
                                    ) : (
                                      <span className="rounded bg-zinc-200 px-1.5 py-0.5 text-zinc-600">
                                        no
                                      </span>
                                    )}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
