import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";
import { API_BASE_URL } from "../config";

interface Trade {
  id: number;
  account_id: number;
  account_alias: string | null;
  contract_display_name: string | null;
  lifecycle: string | null;
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
  realized_pnl: number | null;
  first_executed_at: string | null;
  last_executed_at: string | null;
  is_assigned: boolean;
  assigned_trade_group_id: number | null;
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
  realized_pnl: number | null;
  is_canonical: boolean;
  contract_display: string | null;
  fetched_at: string;
  created_at: string;
  updated_at: string;
}

interface TradeGroupResult {
  id: number;
  account_id: number | null;
  name: string;
  status: string;
  primary_strategy_value: string | null;
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

function tradeGroupLabel(group: TradeGroupResult): string {
  const strategy = group.primary_strategy_value ?? "No Strategy";
  return `${strategy} > ${group.name}`;
}

function TagGroupCell({
  trade,
  onAssigned,
  groupLabel,
}: {
  trade: Trade;
  onAssigned: () => void;
  groupLabel: string | null;
}) {
  const [mode, setMode] = useState<"display" | "search">("display");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TradeGroupResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dropdownPos, setDropdownPos] = useState<{
    top: number;
    left: number;
    flipUp: boolean;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchVersionRef = useRef(0);

  const updateDropdownPos = useCallback(() => {
    if (!inputRef.current) return;
    const rect = inputRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const flipUp = spaceBelow < 260;
    setDropdownPos({
      top: flipUp ? rect.top : rect.bottom + 4,
      left: rect.left,
      flipUp,
    });
  }, []);

  const searchGroups = useCallback(async (searchQuery: string) => {
    const params = new URLSearchParams({
      limit: "20",
      status: "open",
    });
    if (searchQuery.trim()) {
      params.set("q", searchQuery.trim());
    }
    const response = await fetch(
      `${API_BASE_URL}/trade-groups?${params.toString()}`,
    );
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to search trade groups"),
      );
    }
    return (await response.json()) as TradeGroupResult[];
  }, []);

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value);
      setError(null);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      const version = ++searchVersionRef.current;
      debounceRef.current = setTimeout(() => {
        setLoading(true);
        void searchGroups(value)
          .then((data) => {
            if (searchVersionRef.current === version) setResults(data);
          })
          .catch(() => {
            if (searchVersionRef.current === version) setResults([]);
          })
          .finally(() => {
            if (searchVersionRef.current === version) setLoading(false);
          });
      }, 250);
    },
    [searchGroups],
  );

  const openSearch = useCallback(() => {
    setMode("search");
    setQuery("");
    setError(null);
    setLoading(true);
    void searchGroups("")
      .then((data) => setResults(data))
      .catch(() => setResults([]))
      .finally(() => setLoading(false));
    setTimeout(() => {
      inputRef.current?.focus();
      updateDropdownPos();
    }, 0);
  }, [searchGroups, updateDropdownPos]);

  const closeSearch = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    searchVersionRef.current++;
    setMode("display");
    setQuery("");
    setResults([]);
    setError(null);
  }, []);

  // Close dropdown on outside click, scroll, or resize
  useEffect(() => {
    if (mode !== "search") return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        closeSearch();
      }
    };
    const handleScrollOrResize = () => closeSearch();
    document.addEventListener("mousedown", handleOutsideClick);
    window.addEventListener("scroll", handleScrollOrResize, true);
    window.addEventListener("resize", handleScrollOrResize);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
      window.removeEventListener("scroll", handleScrollOrResize, true);
      window.removeEventListener("resize", handleScrollOrResize);
    };
  }, [mode, closeSearch]);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const assignToGroup = async (groupId: number) => {
    setAssigning(true);
    setError(null);
    try {
      const execResponse = await fetch(
        `${API_BASE_URL}/trades/${trade.id}/executions`,
      );
      if (!execResponse.ok) {
        throw new Error(
          await readErrorMessage(execResponse, "Unable to load executions"),
        );
      }
      const tradeExecutions = (await execResponse.json()) as { id: number }[];
      const executionIds = tradeExecutions.map((ex) => ex.id);
      if (executionIds.length === 0) {
        throw new Error("Trade has no executions to assign.");
      }

      const assignResponse = await fetch(
        `${API_BASE_URL}/trade-groups/${groupId}/executions:assign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            execution_ids: executionIds,
            source: "manual",
            created_by: "ui-trader",
            reason: `trade ${trade.id} assigned from trades page`,
            force_reassign: true,
          }),
        },
      );
      if (!assignResponse.ok) {
        throw new Error(
          await readErrorMessage(assignResponse, "Unable to assign trade"),
        );
      }

      closeSearch();
      onAssigned();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Assignment failed");
    } finally {
      setAssigning(false);
    }
  };

  const unassignFromGroup = async () => {
    if (!trade.assigned_trade_group_id) return;
    setAssigning(true);
    setError(null);
    try {
      const execResponse = await fetch(
        `${API_BASE_URL}/trades/${trade.id}/executions`,
      );
      if (!execResponse.ok) {
        throw new Error(
          await readErrorMessage(execResponse, "Unable to load executions"),
        );
      }
      const tradeExecutions = (await execResponse.json()) as { id: number }[];
      const executionIds = tradeExecutions.map((ex) => ex.id);

      const unassignResponse = await fetch(
        `${API_BASE_URL}/trade-groups/${trade.assigned_trade_group_id}/executions:unassign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            execution_ids: executionIds,
            source: "manual",
            created_by: "ui-trader",
            reason: `trade ${trade.id} unassigned from trades page`,
          }),
        },
      );
      if (!unassignResponse.ok) {
        throw new Error(
          await readErrorMessage(unassignResponse, "Unable to unassign trade"),
        );
      }

      onAssigned();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unassign failed");
    } finally {
      setAssigning(false);
    }
  };

  if (mode === "display") {
    if (trade.assigned_trade_group_id) {
      return (
        <div className="flex items-center gap-1">
          <span
            className="rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800 cursor-pointer hover:bg-blue-200"
            onClick={(e) => {
              e.stopPropagation();
              openSearch();
            }}
            title="Click to reassign"
          >
            {groupLabel ?? `Group #${trade.assigned_trade_group_id}`}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (
                window.confirm(
                  `Unassign from group #${trade.assigned_trade_group_id}?`,
                )
              ) {
                void unassignFromGroup();
              }
            }}
            disabled={assigning}
            className="flex h-5 w-5 items-center justify-center rounded text-sm font-bold text-gray-400 hover:bg-red-100 hover:text-red-600 disabled:opacity-50"
            title="Unassign from group"
          >
            ×
          </button>
          {error && (
            <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600">
              {error}
            </span>
          )}
        </div>
      );
    }

    return (
      <button
        onClick={(e) => {
          e.stopPropagation();
          openSearch();
        }}
        className="rounded border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-400 hover:border-blue-300 hover:text-blue-600"
      >
        + Assign
      </button>
    );
  }

  return (
    <div
      ref={containerRef}
      className="relative"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => handleQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") closeSearch();
        }}
        className="w-full min-w-[200px] rounded border border-blue-300 px-2 py-1 text-xs"
        placeholder="Search trade groups..."
        disabled={assigning}
      />
      {dropdownPos && (
        <div
          className="fixed z-50 max-h-[240px] w-[320px] overflow-y-auto rounded border border-gray-200 bg-white shadow-lg"
          style={{
            left: dropdownPos.left,
            ...(dropdownPos.flipUp
              ? { bottom: window.innerHeight - dropdownPos.top + 4 }
              : { top: dropdownPos.top }),
          }}
        >
          {loading && (
            <div className="px-3 py-2 text-xs text-gray-500">Searching...</div>
          )}
          {!loading && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-gray-500">
              No trade groups found.
              <button
                onClick={() => {
                  const params = new URLSearchParams({
                    account_id: String(trade.account_id),
                    prefill_group_name: `${trade.contract_display_name ?? trade.symbol ?? "Trade"} Lifecycle Group`,
                  });
                  window.open(
                    `/tagging?${params.toString()}`,
                    "_blank",
                    "noopener,noreferrer",
                  );
                }}
                className="ml-1 text-blue-600 underline hover:text-blue-800"
              >
                Create one
              </button>
            </div>
          )}
          {!loading &&
            results.map((group) => (
              <button
                key={group.id}
                onClick={() => {
                  void assignToGroup(group.id);
                }}
                disabled={assigning}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs hover:bg-blue-50 disabled:opacity-50"
              >
                <span className="font-medium text-gray-800">
                  {tradeGroupLabel(group)}
                </span>
                <span className="ml-auto text-gray-400">#{group.id}</span>
              </button>
            ))}
          {error && (
            <div className="border-t border-gray-100 px-3 py-2 text-xs text-red-600">
              {error}
            </div>
          )}
        </div>
      )}
    </div>
  );
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
  const [allTradeGroups, setAllTradeGroups] = useState<TradeGroupResult[]>([]);
  const expandedTradeIdRef = useRef<number | null>(null);
  const groupLabelById = useMemo(() => {
    const map = new Map<number, string>();
    for (const group of allTradeGroups) {
      map.set(group.id, tradeGroupLabel(group));
    }
    return map;
  }, [allTradeGroups]);

  const loadTradeGroups = useCallback(async () => {
    const res = await fetch(`${API_BASE_URL}/trade-groups?limit=500`);
    if (!res.ok) return;
    const data: TradeGroupResult[] = await res.json();
    setAllTradeGroups(data);
  }, []);

  const loadTrades = useCallback(async () => {
    const res = await fetch(`${API_BASE_URL}/trades`);
    if (!res.ok) {
      throw new Error(await readErrorMessage(res, "Unable to load trades"));
    }
    const data: Trade[] = await res.json();
    setTrades(data);
    setError(null);
  }, []);

  useEffect(() => {
    void loadTrades()
      .catch((err) => {
        const message =
          err instanceof Error ? err.message : "Unknown trades load error";
        setError(message);
      })
      .finally(() => setLoading(false));
    void loadTradeGroups();

    const timer = window.setInterval(() => {
      void loadTrades().catch(() => {});
    }, 5000);

    return () => {
      window.clearInterval(timer);
    };
  }, [loadTrades, loadTradeGroups]);

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
      expandedTradeIdRef.current = null;
      setExecutions([]);
      return;
    }

    setExpandedTradeId(tradeId);
    expandedTradeIdRef.current = tradeId;
    setExecutionsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/trades/${tradeId}/executions`);
      if (!res.ok) {
        throw new Error(
          await readErrorMessage(res, "Unable to load executions"),
        );
      }
      if (expandedTradeIdRef.current !== tradeId) return;
      const data: TradeExecution[] = await res.json();
      setExecutions(data);
    } catch (err) {
      if (expandedTradeIdRef.current !== tradeId) return;
      const message =
        err instanceof Error ? err.message : "Unable to load executions";
      setError(message);
      setExecutions([]);
    } finally {
      if (expandedTradeIdRef.current === tradeId) setExecutionsLoading(false);
    }
  };

  const handleTradeAssigned = useCallback(() => {
    void loadTrades().catch(() => {});
    void loadTradeGroups().catch(() => {});
  }, [loadTrades, loadTradeGroups]);

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
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Type
              </th>
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Side
              </th>
              <th className="whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Lifecycle
              </th>
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Qty
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Avg Price
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Realized PnL
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Account
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Status
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Tag Group
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
                  colSpan={14}
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
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {trade.sec_type ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {trade.side ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {trade.lifecycle ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {privacyMode ? PRIVACY_MASK : trade.total_quantity}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {formatPrice(trade.avg_price)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {privacyMode
                      ? PRIVACY_MASK
                      : formatPrice(trade.realized_pnl)}
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
                  <td
                    className="px-3 py-2"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <TagGroupCell
                      trade={trade}
                      onAssigned={handleTradeAssigned}
                      groupLabel={
                        trade.assigned_trade_group_id
                          ? (groupLabelById.get(
                              trade.assigned_trade_group_id,
                            ) ?? null)
                          : null
                      }
                    />
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
                    <td colSpan={14} className="p-0">
                      <div className="border-b border-gray-200 bg-gray-50 px-6 py-3">
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
                                  Realized PnL
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
                                    {privacyMode
                                      ? PRIVACY_MASK
                                      : formatPrice(execution.realized_pnl)}
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
