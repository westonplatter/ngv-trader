import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";
import { API_BASE_URL } from "../config";
import { useSSE } from "../lib/events";

interface TradeExecutionRow {
  id: number;
  trade_id: number;
  account_id: number;
  account_alias: string | null;
  ib_exec_id: string;
  exec_role: string;
  sec_type: string | null;
  executed_at: string;
  quantity: number;
  price: number;
  side: string | null;
  exchange: string | null;
  commission: number | null;
  realized_pnl: number | null;
  is_canonical: boolean;
  contract_display: string | null;
  parent_ib_exec_id: string | null;
  trade_ib_perm_id: number | null;
  trade_order_ref: string | null;
  trade_status: string;
  trade_lifecycle: string | null;
  trade_contract_display_name: string | null;
  trade_realized_pnl: number | null;
  trade_assigned_trade_group_id: number | null;
  trade_first_executed_at: string | null;
  trade_last_executed_at: string | null;
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

function execRoleBadge(role: string): { label: string; className: string } {
  if (role === "combo_summary") {
    return { label: "COMBO", className: "bg-indigo-100 text-indigo-800" };
  }
  if (role === "leg") {
    return { label: "LEG", className: "bg-amber-100 text-amber-800" };
  }
  return { label: "—", className: "bg-gray-100 text-gray-700" };
}

function TagGroupCell({
  tradeId,
  accountId,
  contractDisplayName,
  assignedTradeGroupId,
  groupLabel,
  onAssigned,
}: {
  tradeId: number;
  accountId: number;
  contractDisplayName: string | null;
  assignedTradeGroupId: number | null;
  groupLabel: string | null;
  onAssigned: () => void;
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
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchVersionRef = useRef(0);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

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
    const params = new URLSearchParams({ limit: "20", status: "open" });
    if (searchQuery.trim()) params.set("q", searchQuery.trim());
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
      inputRef.current?.focus({ preventScroll: true });
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
    document.addEventListener("mousedown", handleOutsideClick);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, [mode, closeSearch]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Reset the highlighted option whenever the result set changes.
  useEffect(() => {
    setHighlightedIndex(0);
  }, [results]);

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    itemRefs.current[highlightedIndex]?.scrollIntoView({ block: "nearest" });
  }, [highlightedIndex]);

  const assignToGroup = async (groupId: number) => {
    setAssigning(true);
    setError(null);
    try {
      const execResponse = await fetch(
        `${API_BASE_URL}/trades/${tradeId}/executions`,
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
            reason: `trade ${tradeId} assigned from trades page`,
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
    if (!assignedTradeGroupId) return;
    setAssigning(true);
    setError(null);
    try {
      const execResponse = await fetch(
        `${API_BASE_URL}/trades/${tradeId}/executions`,
      );
      if (!execResponse.ok) {
        throw new Error(
          await readErrorMessage(execResponse, "Unable to load executions"),
        );
      }
      const tradeExecutions = (await execResponse.json()) as { id: number }[];
      const executionIds = tradeExecutions.map((ex) => ex.id);

      const unassignResponse = await fetch(
        `${API_BASE_URL}/trade-groups/${assignedTradeGroupId}/executions:unassign`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            execution_ids: executionIds,
            source: "manual",
            created_by: "ui-trader",
            reason: `trade ${tradeId} unassigned from trades page`,
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
    if (assignedTradeGroupId) {
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
            {groupLabel ?? `Group #${assignedTradeGroupId}`}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (
                window.confirm(`Unassign from group #${assignedTradeGroupId}?`)
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
          if (e.key === "Escape") {
            closeSearch();
          } else if (e.key === "ArrowDown") {
            if (results.length === 0) return;
            e.preventDefault();
            setHighlightedIndex((prev) => (prev + 1) % results.length);
          } else if (e.key === "ArrowUp") {
            if (results.length === 0) return;
            e.preventDefault();
            setHighlightedIndex(
              (prev) => (prev - 1 + results.length) % results.length,
            );
          } else if (e.key === "Enter") {
            const group = results[highlightedIndex];
            if (group && !assigning) {
              e.preventDefault();
              void assignToGroup(group.id);
            }
          }
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
                    account_id: String(accountId),
                    prefill_group_name: `${contractDisplayName ?? "Trade"} Lifecycle Group`,
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
            results.map((group, index) => (
              <button
                key={group.id}
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => {
                  void assignToGroup(group.id);
                }}
                disabled={assigning}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs disabled:opacity-50 ${
                  index === highlightedIndex ? "bg-blue-50" : "hover:bg-blue-50"
                }`}
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
  const [executions, setExecutions] = useState<TradeExecutionRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [symbolFilter, setSymbolFilter] = useState("");
  const [accountFilter, setAccountFilter] = useState<string>("all");
  const [timeRange, setTimeRange] = useState<string>("all");
  const [highlightedTradeId, setHighlightedTradeId] = useState<number | null>(
    null,
  );
  const [highlightedSymbol, setHighlightedSymbol] = useState<string | null>(
    null,
  );
  const [allTradeGroups, setAllTradeGroups] = useState<TradeGroupResult[]>([]);

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

  const serverSymbol = useMemo(() => {
    const raw = symbolFilter.trim();
    return /^[A-Za-z0-9]+$/.test(raw) ? raw.toUpperCase() : null;
  }, [symbolFilter]);

  const loadExecutions = useCallback(async () => {
    const params = new URLSearchParams({ limit: "5000" });
    if (serverSymbol) params.set("symbol", serverSymbol);
    const res = await fetch(
      `${API_BASE_URL}/trade-executions?${params.toString()}`,
    );
    if (!res.ok) {
      throw new Error(await readErrorMessage(res, "Unable to load executions"));
    }
    const data: TradeExecutionRow[] = await res.json();
    setExecutions(data);
    setError(null);
  }, [serverSymbol]);

  useEffect(() => {
    void loadExecutions()
      .catch((err) => {
        const message =
          err instanceof Error ? err.message : "Unknown executions load error";
        setError(message);
      })
      .finally(() => setLoading(false));
    void loadTradeGroups();
  }, [loadExecutions, loadTradeGroups]);

  useSSE<Record<string, unknown>>("trades", () => {
    void loadExecutions().catch(() => {});
    void loadTradeGroups().catch(() => {});
  });

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
    for (const row of executions) {
      const key = String(row.account_id);
      if (!seen.has(key)) {
        seen.set(key, row.account_alias ?? `Account ${row.account_id}`);
      }
    }
    return Array.from(seen.entries()).map(([id, label]) => ({ id, label }));
  }, [executions]);

  const filteredRows = useMemo(() => {
    let next = executions;
    if (accountFilter !== "all") {
      next = next.filter((row) => String(row.account_id) === accountFilter);
    }
    if (symbolRegex) {
      next = next.filter((row) =>
        symbolRegex.test(
          row.contract_display ?? row.trade_contract_display_name ?? "",
        ),
      );
    }
    if (timeRange !== "all") {
      const hoursMap: Record<string, number> = {
        "24h": 24,
        "3d": 72,
        "7d": 168,
        "30d": 720,
        "90d": 2160,
      };
      const hours = hoursMap[timeRange];
      if (hours) {
        const cutoff = Date.now() - hours * 60 * 60 * 1000;
        next = next.filter((row) => Date.parse(row.executed_at) >= cutoff);
      }
    }
    return next;
  }, [executions, accountFilter, symbolRegex, timeRange]);

  // For each trade_id, the row that owns the Tag Group cell.
  // Prefer combo_summary; otherwise the earliest row in the filtered view.
  const tagGroupRowIdByTradeId = useMemo(() => {
    const map = new Map<number, number>();
    for (const row of filteredRows) {
      if (row.exec_role === "combo_summary") {
        map.set(row.trade_id, row.id);
      }
    }
    for (const row of filteredRows) {
      if (!map.has(row.trade_id)) {
        map.set(row.trade_id, row.id);
      } else {
        const currentId = map.get(row.trade_id)!;
        const current = filteredRows.find((r) => r.id === currentId);
        if (
          current &&
          current.exec_role !== "combo_summary" &&
          Date.parse(row.executed_at) < Date.parse(current.executed_at)
        ) {
          map.set(row.trade_id, row.id);
        }
      }
    }
    return map;
  }, [filteredRows]);

  const kickOffTradesSync = async (
    label: string,
    options: { days?: number; sinceLastTrade?: boolean },
  ) => {
    setSyncing(true);
    setSyncMessage(null);
    setSyncError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/trades/sync/flex-query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: `${label} (flex query) from Trades page.`,
          max_attempts: 3,
          ...(options.days !== undefined ? { days: options.days } : {}),
          ...(options.sinceLastTrade ? { since_last_trade: true } : {}),
        }),
      });
      if (!res.ok) {
        throw new Error(await readErrorMessage(res, "Unable to queue sync"));
      }
      const data: {
        job_id: number;
        status: string;
        start_date?: string | null;
        end_date?: string | null;
      } = await res.json();
      const rangeNote =
        data.start_date && data.end_date
          ? ` Syncing ${data.start_date} → ${data.end_date}.`
          : "";
      setSyncMessage(
        `Queued ${label.toLowerCase()} job #${data.job_id} (${data.status}).${rangeNote}`,
      );
      window.setTimeout(() => {
        void loadExecutions().catch(() => {});
      }, 2000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setSyncing(false);
    }
  };

  const handleTradeAssigned = useCallback(() => {
    void loadExecutions().catch(() => {});
    void loadTradeGroups().catch(() => {});
  }, [loadExecutions, loadTradeGroups]);

  const toggleHighlight = (tradeId: number) => {
    setHighlightedTradeId((current) => (current === tradeId ? null : tradeId));
  };

  const toggleSymbolHighlight = (symbol: string | null) => {
    if (!symbol || symbol === "-") return;
    setHighlightedSymbol((current) => (current === symbol ? null : symbol));
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Trades</h2>
          <p className="text-xs text-gray-500">
            {filteredRows.length} execution(s)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              void kickOffTradesSync("Quick sync", { days: 1 });
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Quick Sync (1d)"}
          </button>
          <button
            onClick={() => {
              void kickOffTradesSync("Full sync", { days: 7 });
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Full Sync (7d)"}
          </button>
          <button
            onClick={() => {
              void kickOffTradesSync("Extended sync", { days: 30 });
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Extended Sync (30d)"}
          </button>
          <button
            onClick={() => {
              void kickOffTradesSync("Sync since last trade", {
                sinceLastTrade: true,
              });
            }}
            disabled={syncing}
            title="Sync from the most recent trade date across all accounts through today"
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Sync Since Last Trade"}
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
          { id: "30d", label: "30d" },
          { id: "90d", label: "90d" },
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
      {loading && <p className="text-gray-500">Loading executions...</p>}
      {error && <p className="text-red-600">Error: {error}</p>}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Time
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
              <th className="w-12 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Role
              </th>
              <th className="w-16 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Action
              </th>
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Type
              </th>
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Side
              </th>
              <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
                Qty
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Price
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
                Exec ID
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Parent Exec ID
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Order Ref
              </th>
            </tr>
          </thead>
          <tbody>
            {!loading && filteredRows.length === 0 && (
              <tr>
                <td
                  colSpan={15}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  No executions found.
                </td>
              </tr>
            )}
            {filteredRows.map((row) => {
              const ownsTagCell =
                tagGroupRowIdByTradeId.get(row.trade_id) === row.id;
              const isHighlighted = highlightedTradeId === row.trade_id;
              const symbol =
                row.contract_display ?? row.trade_contract_display_name ?? "-";
              const isSymbolHighlighted =
                highlightedSymbol !== null && symbol === highlightedSymbol;
              const role = execRoleBadge(row.exec_role);
              return (
                <tr
                  key={row.id}
                  className={`border-b border-gray-200 ${
                    isHighlighted ? "bg-yellow-50" : "hover:bg-gray-50"
                  }`}
                >
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {formatDateTime(row.executed_at)}
                  </td>
                  <td
                    onDoubleClick={() => toggleSymbolHighlight(symbol)}
                    title="Double-click to highlight matching contracts"
                    className={`cursor-pointer select-none whitespace-nowrap px-3 py-2 font-medium ${
                      isSymbolHighlighted
                        ? "bg-red-200 text-red-900"
                        : "text-gray-800"
                    }`}
                  >
                    {symbol}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">
                    <span
                      className={`rounded px-1.5 py-0.5 font-medium ${role.className}`}
                    >
                      {role.label}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs">
                    {row.trade_lifecycle ? (
                      <span
                        className={`rounded px-1.5 py-0.5 font-medium ${
                          row.trade_lifecycle === "Open"
                            ? "bg-green-100 text-green-800"
                            : row.trade_lifecycle === "Close"
                              ? "bg-red-100 text-red-800"
                              : "bg-purple-100 text-purple-800"
                        }`}
                      >
                        {row.trade_lifecycle}
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {row.sec_type ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {row.side ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {privacyMode ? PRIVACY_MASK : row.quantity}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {formatPrice(row.price)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {privacyMode ? PRIVACY_MASK : formatPrice(row.realized_pnl)}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-800">
                    {row.account_alias ?? `Account ${row.account_id}`}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[row.trade_status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {row.trade_status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    {ownsTagCell ? (
                      <TagGroupCell
                        tradeId={row.trade_id}
                        accountId={row.account_id}
                        contractDisplayName={
                          row.trade_contract_display_name ??
                          row.contract_display
                        }
                        assignedTradeGroupId={row.trade_assigned_trade_group_id}
                        groupLabel={
                          row.trade_assigned_trade_group_id
                            ? (groupLabelById.get(
                                row.trade_assigned_trade_group_id,
                              ) ?? null)
                            : null
                        }
                        onAssigned={handleTradeAssigned}
                      />
                    ) : null}
                  </td>
                  <td className="max-w-[200px] truncate whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-600">
                    {privacyMode ? PRIVACY_MASK : row.ib_exec_id}
                  </td>
                  <td className="max-w-[200px] truncate whitespace-nowrap px-3 py-2 font-mono text-xs">
                    {(() => {
                      const isParentRow = row.exec_role === "combo_summary";
                      const parentId =
                        row.parent_ib_exec_id ??
                        (isParentRow ? row.ib_exec_id : null);
                      if (!parentId)
                        return <span className="text-gray-400">—</span>;
                      const baseClass = isHighlighted
                        ? "bg-yellow-200 text-yellow-900"
                        : isParentRow
                          ? "text-gray-400 hover:text-gray-600"
                          : "text-blue-600 hover:text-blue-800";
                      return (
                        <button
                          onClick={() => toggleHighlight(row.trade_id)}
                          className={`rounded px-1.5 py-0.5 hover:bg-yellow-100 ${baseClass}`}
                          title={
                            isParentRow
                              ? "This row is the parent — click to highlight the group"
                              : "Highlight sibling executions"
                          }
                        >
                          {isParentRow && (
                            <span className="mr-1" aria-hidden="true">
                              ⤴
                            </span>
                          )}
                          {privacyMode ? PRIVACY_MASK : parentId}
                        </button>
                      );
                    })()}
                  </td>
                  <td className="max-w-[160px] truncate whitespace-nowrap px-3 py-2 text-xs text-gray-600">
                    {row.trade_order_ref ?? "-"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
