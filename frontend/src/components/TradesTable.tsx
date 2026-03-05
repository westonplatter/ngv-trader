import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";
import { API_BASE_URL } from "../config";

interface Trade {
  id: number;
  account_id: number;
  account_alias: string | null;
  contract_display_name: string | null;
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

interface Strategy {
  id: number;
  value: string;
}

interface TradeGroup {
  id: number;
  account_id: number;
  name: string;
  status: "open" | "closed" | "archived";
}

const STATUS_CLASS: Record<string, string> = {
  filled: "bg-emerald-100 text-emerald-800",
  partial: "bg-blue-100 text-blue-800",
  cancelled: "bg-zinc-200 text-zinc-800",
  unknown: "bg-gray-100 text-gray-800",
};

function formatDateTime(value: string | null | undefined): string {
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

function formatPrice(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

async function readErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return `${payload.detail} (${response.status})`;
    }
  } catch {
    // no-op
  }
  return `${fallback} (${response.status})`;
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

  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [strategyQuery, setStrategyQuery] = useState("");
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(
    null,
  );
  const [tradeGroups, setTradeGroups] = useState<TradeGroup[]>([]);
  const [selectedTradeGroupId, setSelectedTradeGroupId] = useState<string>("");
  const [associationMessage, setAssociationMessage] = useState<string | null>(
    null,
  );
  const [associationError, setAssociationError] = useState<string | null>(null);

  const loadTrades = useCallback(async () => {
    const res = await fetch(`${API_BASE_URL}/trades`);
    if (!res.ok) {
      throw new Error(await readErrorMessage(res, "Unable to load trades"));
    }
    const data: Trade[] = await res.json();
    setTrades(data);
    setError(null);
  }, []);

  const loadStrategies = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/strategies?limit=500`);
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load strategies"),
      );
    }
    const data: Strategy[] = await response.json();
    setStrategies(data);
  }, []);

  const loadTradeGroups = useCallback(async (strategyValue: string) => {
    const params = new URLSearchParams({
      limit: "200",
      status: "open",
      strategy_tag: strategyValue,
    });
    const response = await fetch(
      `${API_BASE_URL}/trade-groups?${params.toString()}`,
    );
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load trade groups"),
      );
    }
    const data: TradeGroup[] = await response.json();
    setTradeGroups(data);
    setSelectedTradeGroupId("");
  }, []);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/trades`);
        if (!res.ok) {
          throw new Error(await readErrorMessage(res, "Unable to load trades"));
        }
        const data: Trade[] = await res.json();
        if (!active) return;
        setTrades(data);
        setError(null);
      } catch (err) {
        if (!active) return;
        const message =
          err instanceof Error ? err.message : "Unknown trades load error";
        setError(message);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    void loadStrategies().catch((err: unknown) => {
      const message =
        err instanceof Error ? err.message : "Failed to load strategies.";
      if (active) setAssociationError(message);
    });

    const timer = window.setInterval(() => {
      void load();
    }, 5000);

    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [loadStrategies]);

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
    for (const trade of trades) {
      const key = String(trade.account_id);
      if (!seen.has(key)) {
        seen.set(key, trade.account_alias ?? `Account ${trade.account_id}`);
      }
    }
    return Array.from(seen.entries()).map(([id, label]) => ({ id, label }));
  }, [trades]);

  const filteredTrades = useMemo(() => {
    let next = trades;
    if (accountFilter !== "all") {
      next = next.filter((trade) => String(trade.account_id) === accountFilter);
    }
    if (symbolRegex) {
      next = next.filter((trade) =>
        symbolRegex.test(trade.contract_display_name ?? trade.symbol ?? ""),
      );
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
        next = next.filter((trade) => {
          const ts = trade.last_executed_at ?? trade.first_executed_at;
          if (!ts) return false;
          return Date.parse(ts) >= cutoff;
        });
      }
    }
    return next;
  }, [trades, accountFilter, symbolRegex, timeRange]);

  const strategyMatches = useMemo(() => {
    const query = strategyQuery.trim().toLowerCase();
    if (!query) return strategies.slice(0, 100);
    return strategies
      .filter((strategy) => strategy.value.toLowerCase().includes(query))
      .slice(0, 100);
  }, [strategies, strategyQuery]);

  const selectedStrategy = useMemo(
    () =>
      strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [strategies, selectedStrategyId],
  );

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
      if (!res.ok) {
        throw new Error(await readErrorMessage(res, "Unable to queue sync"));
      }
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(
        `Queued ${label.toLowerCase()} job #${data.job_id} (${data.status}).`,
      );
      window.setTimeout(() => {
        void loadTrades().catch(() => {
          // no-op
        });
      }, 2000);
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
      setAssociationError(null);
      setAssociationMessage(null);
      return;
    }

    setExpandedTradeId(tradeId);
    setExecutionsLoading(true);
    setAssociationError(null);
    setAssociationMessage(null);

    try {
      const res = await fetch(`${API_BASE_URL}/trades/${tradeId}/executions`);
      if (!res.ok) {
        throw new Error(
          await readErrorMessage(res, "Unable to load executions"),
        );
      }
      const data: TradeExecution[] = await res.json();
      setExecutions(data);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unable to load executions";
      setAssociationError(message);
      setExecutions([]);
    } finally {
      setExecutionsLoading(false);
    }
  };

  const handleStrategyInputChange = (value: string) => {
    setStrategyQuery(value);
    const matched = strategies.find(
      (strategy) => strategy.value.toLowerCase() === value.toLowerCase(),
    );
    setSelectedStrategyId(matched ? matched.id : null);
    setTradeGroups([]);
    setSelectedTradeGroupId("");
  };

  const searchTradeGroupsForStrategy = async () => {
    if (!selectedStrategy) {
      setAssociationError("Select a strategy from autocomplete first.");
      return;
    }

    setAssociationError(null);
    setAssociationMessage(null);
    try {
      await loadTradeGroups(selectedStrategy.value);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load trade groups";
      setAssociationError(message);
    }
  };

  const associateTradeWithGroup = async (trade: Trade) => {
    if (!selectedTradeGroupId) {
      setAssociationError("Select a trade group to associate this trade.");
      return;
    }

    setAssociationError(null);
    setAssociationMessage(null);

    try {
      const executionsResponse = await fetch(
        `${API_BASE_URL}/trades/${trade.id}/executions`,
      );
      if (!executionsResponse.ok) {
        throw new Error(
          await readErrorMessage(
            executionsResponse,
            "Unable to load trade executions",
          ),
        );
      }
      const tradeExecutions: TradeExecution[] = await executionsResponse.json();
      const executionIds = tradeExecutions.map((execution) => execution.id);
      if (executionIds.length === 0) {
        throw new Error("Trade has no executions to associate.");
      }

      const assignResponse = await fetch(
        `${API_BASE_URL}/trade-groups/${Number(selectedTradeGroupId)}/executions:assign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            execution_ids: executionIds,
            source: "manual",
            created_by: "ui-trader",
            reason: `trade ${trade.id} associated from trades page`,
            force_reassign: true,
          }),
        },
      );
      if (!assignResponse.ok) {
        throw new Error(
          await readErrorMessage(assignResponse, "Unable to associate trade"),
        );
      }

      setAssociationMessage(
        `Associated trade #${trade.id} (${executionIds.length} execution${executionIds.length > 1 ? "s" : ""}) to group #${selectedTradeGroupId}.`,
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Association failed";
      setAssociationError(message);
    }
  };

  const openCreateTradeGroupTab = (trade: Trade) => {
    const params = new URLSearchParams({
      account_id: String(trade.account_id),
      prefill_group_name: `${trade.contract_display_name ?? trade.symbol ?? "Trade"} Lifecycle Group`,
    });
    if (selectedStrategyId) {
      params.set("strategy_id", String(selectedStrategyId));
    }
    window.open(
      `/tagging?${params.toString()}`,
      "_blank",
      "noopener,noreferrer",
    );
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
              <th className="w-8 whitespace-nowrap px-3 py-2 font-semibold text-gray-700" />
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Last Exec
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                <div className="space-y-1">
                  <input
                    value={symbolFilter}
                    onChange={(event) => setSymbolFilter(event.target.value)}
                    placeholder="Filter"
                    className="w-24 rounded border border-gray-300 px-2 py-0.5 text-xs font-normal text-gray-700"
                  />
                  <div>Contract</div>
                </div>
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Type
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Side
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Qty
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Avg Price
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Account
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Status
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Perm ID
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
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
              <Fragment key={trade.id}>
                <tr
                  onClick={() => {
                    void toggleExecutions(trade.id);
                  }}
                  className="cursor-pointer border-b border-gray-200 hover:bg-gray-50"
                >
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-400">
                    {expandedTradeId === trade.id ? "▼" : "▶"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {formatDateTime(trade.last_executed_at)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-medium text-gray-800">
                    {trade.contract_display_name ?? trade.symbol ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {trade.sec_type ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {trade.side ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {privacyMode ? PRIVACY_MASK : trade.total_quantity}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {formatPrice(trade.avg_price)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-800">
                    {trade.account_alias ?? `Account ${trade.account_id}`}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[trade.status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {trade.status}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-gray-600">
                    {privacyMode ? PRIVACY_MASK : (trade.ib_perm_id ?? "-")}
                  </td>
                  <td className="max-w-[160px] truncate whitespace-nowrap px-3 py-2 text-xs text-gray-600">
                    {trade.order_ref ?? "-"}
                  </td>
                </tr>
                {expandedTradeId === trade.id && (
                  <tr>
                    <td colSpan={11} className="p-0">
                      <div className="space-y-3 border-b border-gray-200 bg-gray-50 px-6 py-3">
                        <div className="rounded border border-blue-200 bg-blue-50 p-3">
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-800">
                            Associate Trade To Trade Group
                          </h4>
                          <div className="grid grid-cols-1 gap-2 xl:grid-cols-[minmax(220px,1fr)_auto_minmax(220px,1fr)_auto_auto]">
                            <div>
                              <label className="mb-1 block text-xs text-gray-700">
                                Strategy (autocomplete)
                              </label>
                              <input
                                list="strategy-options"
                                value={strategyQuery}
                                onChange={(event) =>
                                  handleStrategyInputChange(event.target.value)
                                }
                                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                                placeholder="Search active strategies"
                              />
                              <datalist id="strategy-options">
                                {strategyMatches.map((strategy) => (
                                  <option
                                    key={strategy.id}
                                    value={strategy.value}
                                  />
                                ))}
                              </datalist>
                            </div>
                            <div className="flex items-end">
                              <button
                                onClick={() => {
                                  void searchTradeGroupsForStrategy();
                                }}
                                className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-100"
                              >
                                Find Groups
                              </button>
                            </div>
                            <div>
                              <label className="mb-1 block text-xs text-gray-700">
                                Trade Group
                              </label>
                              <select
                                value={selectedTradeGroupId}
                                onChange={(event) =>
                                  setSelectedTradeGroupId(event.target.value)
                                }
                                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                              >
                                <option value="">Select trade group</option>
                                {tradeGroups
                                  .filter(
                                    (group) =>
                                      group.account_id === trade.account_id,
                                  )
                                  .map((group) => (
                                    <option key={group.id} value={group.id}>
                                      #{group.id} - {group.name} ({group.status}
                                      )
                                    </option>
                                  ))}
                              </select>
                            </div>
                            <div className="flex items-end">
                              <button
                                onClick={() => {
                                  void associateTradeWithGroup(trade);
                                }}
                                className="rounded border border-emerald-300 px-3 py-1 text-sm text-emerald-700 hover:bg-emerald-100"
                              >
                                Associate Trade
                              </button>
                            </div>
                            <div className="flex items-end">
                              <button
                                onClick={() => openCreateTradeGroupTab(trade)}
                                className="rounded border border-amber-300 px-3 py-1 text-sm text-amber-700 hover:bg-amber-100"
                              >
                                Create Group In New Tab
                              </button>
                            </div>
                          </div>
                          {associationMessage && (
                            <p className="mt-2 text-xs text-green-700">
                              {associationMessage}
                            </p>
                          )}
                          {associationError && (
                            <p className="mt-2 text-xs text-red-700">
                              {associationError}
                            </p>
                          )}
                        </div>

                        <div>
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-600">
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
                                  <th className="px-2 py-1 font-medium">
                                    Time
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    Contract
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    Role
                                  </th>
                                  <th className="px-2 py-1 font-medium">
                                    Side
                                  </th>
                                  <th className="px-2 py-1 font-medium">Qty</th>
                                  <th className="px-2 py-1 font-medium">
                                    Price
                                  </th>
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
                                {executions.map((execution) => (
                                  <tr
                                    key={execution.id}
                                    className={`border-t border-gray-200 ${!execution.is_canonical ? "opacity-50" : ""}`}
                                  >
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {formatDateTime(execution.executed_at)}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 font-medium text-gray-800">
                                      {execution.contract_display ?? "-"}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {execution.exec_role === "combo_summary"
                                        ? "COMBO"
                                        : execution.exec_role === "leg"
                                          ? "LEG"
                                          : "-"}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {execution.side ?? "-"}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {privacyMode
                                        ? PRIVACY_MASK
                                        : execution.quantity}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {formatPrice(execution.price)}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {formatPrice(execution.commission)}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-700">
                                      {execution.exchange ?? "-"}
                                    </td>
                                    <td className="max-w-[200px] truncate whitespace-nowrap px-2 py-1 font-mono text-gray-500">
                                      {privacyMode
                                        ? PRIVACY_MASK
                                        : execution.ib_exec_id}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1 text-gray-600">
                                      .
                                      {String(execution.exec_revision).padStart(
                                        2,
                                        "0",
                                      )}
                                    </td>
                                    <td className="whitespace-nowrap px-2 py-1">
                                      {execution.is_canonical ? (
                                        <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-medium text-emerald-700">
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
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
