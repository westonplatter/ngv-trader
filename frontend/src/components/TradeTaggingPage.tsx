import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../config";

type TradeGroup = {
  id: number;
  account_id: number;
  name: string;
  notes: string | null;
  status: "open" | "closed" | "archived";
  opened_at: string;
  closed_at: string | null;
};

type Trade = {
  id: number;
  account_id: number;
  account_alias: string | null;
  contract_display_name: string | null;
  symbol: string | null;
  status: string;
  is_assigned: boolean;
  last_executed_at: string | null;
};

type TradeExecution = {
  id: number;
  trade_id: number;
  account_id: number;
  executed_at: string;
  quantity: number;
  price: number;
  side: string | null;
  exec_role: string;
  contract_display: string | null;
};

type TimelineEvent = {
  event_id: string;
  event_type: string;
  occurred_at: string;
  execution_id: number | null;
  related_trade_group_id: number | null;
  summary: string;
};

type Tag = {
  id: number;
  tag_type: string;
  value: string;
  normalized_value: string;
  created_by: string;
  created_at: string;
};

type Account = {
  id: number;
  account: string;
  masked_account: string | null;
  alias: string | null;
};

function formatDate(value: string | null): string {
  if (!value) return "-";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "-";
  return new Date(parsed).toLocaleString();
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

function statusClassName(status: TradeGroup["status"]): string {
  if (status === "open") return "bg-emerald-100 text-emerald-800";
  if (status === "closed") return "bg-gray-100 text-gray-700";
  return "bg-amber-100 text-amber-800";
}

function accountLabel(account: Account): string {
  if (account.alias && account.alias.trim()) return account.alias.trim();
  if (account.masked_account && account.masked_account.trim())
    return account.masked_account.trim();
  return account.account;
}

export default function TradeTaggingPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [strategies, setStrategies] = useState<Tag[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(
    null,
  );

  const [groups, setGroups] = useState<TradeGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);

  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTradeId, setSelectedTradeId] = useState<number | null>(null);
  const [tradeAccountFilter, setTradeAccountFilter] = useState<string>("all");
  const [tradeAssignmentFilter, setTradeAssignmentFilter] = useState<
    "all" | "assigned" | "unassigned"
  >("all");
  const [tradeSearchQuery, setTradeSearchQuery] = useState("");
  const [executions, setExecutions] = useState<TradeExecution[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);

  const [newStrategyValue, setNewStrategyValue] = useState("");
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupNotes, setNewGroupNotes] = useState("");
  const [newGroupAccountId, setNewGroupAccountId] = useState("1");

  const [loading, setLoading] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedStrategy = useMemo(
    () =>
      strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [selectedStrategyId, strategies],
  );

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );

  const accountLabelById = useMemo(() => {
    const labels = new Map<number, string>();
    for (const account of accounts) {
      labels.set(account.id, accountLabel(account));
    }
    return labels;
  }, [accounts]);

  const filteredTrades = useMemo(() => {
    const query = tradeSearchQuery.trim().toLowerCase();
    return trades.filter((trade) => {
      if (
        tradeAccountFilter !== "all" &&
        trade.account_id !== Number(tradeAccountFilter)
      )
        return false;
      if (tradeAssignmentFilter === "assigned" && !trade.is_assigned)
        return false;
      if (tradeAssignmentFilter === "unassigned" && trade.is_assigned)
        return false;
      if (!query) return true;
      const contract = (
        trade.contract_display_name ??
        trade.symbol ??
        ""
      ).toLowerCase();
      const account = (
        accountLabelById.get(trade.account_id) ?? ""
      ).toLowerCase();
      return (
        contract.includes(query) ||
        account.includes(query) ||
        String(trade.id).includes(query)
      );
    });
  }, [
    accountLabelById,
    tradeAccountFilter,
    tradeAssignmentFilter,
    tradeSearchQuery,
    trades,
  ]);

  const loadStrategies = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/strategies?limit=200`);
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load strategies"),
      );
    }
    const data: Tag[] = await response.json();
    setStrategies(data);
    setSelectedStrategyId((current) => {
      if (data.length === 0) return null;
      if (current && data.some((strategy) => strategy.id === current))
        return current;
      return data[0].id;
    });
  }, []);

  const loadAccounts = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/accounts`);
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load accounts"),
      );
    }
    const data: Account[] = await response.json();
    setAccounts(data);
    setNewGroupAccountId((current) => {
      if (data.length === 0) return "";
      if (current && data.some((account) => String(account.id) === current))
        return current;
      return String(data[0].id);
    });
  }, []);

  const loadGroups = useCallback(async (strategyValue: string | null) => {
    if (!strategyValue) {
      setGroups([]);
      setSelectedGroupId(null);
      return;
    }

    const params = new URLSearchParams({
      limit: "200",
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
    setGroups(data);
    setSelectedGroupId((current) => {
      if (data.length === 0) return null;
      if (current && data.some((group) => group.id === current)) return current;
      return data[0].id;
    });
  }, []);

  const loadTrades = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/trades?limit=100`);
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load trades"),
      );
    }
    const data: Trade[] = await response.json();
    setTrades(data);
  }, []);

  const loadTimeline = useCallback(async (tradeGroupId: number) => {
    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${tradeGroupId}/timeline`,
    );
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load timeline"),
      );
    }
    const data: { events: TimelineEvent[] } = await response.json();
    setTimeline(data.events);
  }, []);

  const fetchTradeExecutions = useCallback(
    async (tradeId: number): Promise<TradeExecution[]> => {
      const response = await fetch(
        `${API_BASE_URL}/trades/${tradeId}/executions`,
      );
      if (!response.ok) {
        throw new Error(
          await readErrorMessage(response, "Unable to load executions"),
        );
      }
      return (await response.json()) as TradeExecution[];
    },
    [],
  );

  const loadExecutions = useCallback(
    async (tradeId: number) => {
      const data = await fetchTradeExecutions(tradeId);
      setExecutions(data);
    },
    [fetchTradeExecutions],
  );

  useEffect(() => {
    let active = true;

    Promise.all([loadStrategies(), loadTrades(), loadAccounts()])
      .catch((loadError: unknown) => {
        if (!active) return;
        const nextMessage =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load trade tagging workspace.";
        setError(nextMessage);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [loadAccounts, loadStrategies, loadTrades]);

  useEffect(() => {
    let active = true;

    if (!selectedStrategy) {
      setGroups([]);
      setSelectedGroupId(null);
      return;
    }

    setLoadingGroups(true);
    void loadGroups(selectedStrategy.value)
      .catch((groupError: unknown) => {
        if (!active) return;
        const nextMessage =
          groupError instanceof Error
            ? groupError.message
            : "Failed to load trade groups.";
        setError(nextMessage);
      })
      .finally(() => {
        if (active) setLoadingGroups(false);
      });

    return () => {
      active = false;
    };
  }, [loadGroups, selectedStrategy]);

  useEffect(() => {
    if (selectedGroupId == null) {
      setTimeline([]);
      return;
    }

    void loadTimeline(selectedGroupId).catch((timelineError: unknown) => {
      const nextMessage =
        timelineError instanceof Error
          ? timelineError.message
          : "Failed to load trade group timeline.";
      setError(nextMessage);
    });
  }, [loadTimeline, selectedGroupId]);

  useEffect(() => {
    if (selectedTradeId == null) {
      setExecutions([]);
      return;
    }

    void loadExecutions(selectedTradeId).catch((executionError: unknown) => {
      const nextMessage =
        executionError instanceof Error
          ? executionError.message
          : "Failed to load executions.";
      setError(nextMessage);
    });
  }, [loadExecutions, selectedTradeId]);

  useEffect(() => {
    if (selectedTradeId == null) return;
    if (filteredTrades.some((trade) => trade.id === selectedTradeId)) return;
    setSelectedTradeId(null);
  }, [filteredTrades, selectedTradeId]);

  const createStrategy = async () => {
    if (!newStrategyValue.trim()) {
      setError("Strategy value is required.");
      return;
    }

    setError(null);
    setMessage(null);

    const response = await fetch(`${API_BASE_URL}/strategies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        value: newStrategyValue.trim(),
        created_by: "ui-trader",
      }),
    });

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to create strategy"),
      );
    }

    const createdStrategy: Tag = await response.json();
    setNewStrategyValue("");
    setMessage("Created strategy.");
    await loadStrategies();
    setSelectedStrategyId(createdStrategy.id);
  };

  const createGroup = async () => {
    if (!selectedStrategyId) {
      setError("Select a strategy before creating a trade group.");
      return;
    }
    if (!newGroupAccountId) {
      setError("Select an account before creating a trade group.");
      return;
    }
    if (!newGroupName.trim()) {
      setError("Trade group name is required.");
      return;
    }

    setError(null);
    setMessage(null);

    const response = await fetch(`${API_BASE_URL}/trade-groups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        account_id: Number(newGroupAccountId),
        name: newGroupName.trim(),
        notes: newGroupNotes.trim() || null,
        strategy_tag_id: selectedStrategyId,
        source: "manual",
        created_by: "ui-trader",
      }),
    });

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to create trade group"),
      );
    }

    const createdGroup: TradeGroup = await response.json();
    setNewGroupName("");
    setNewGroupNotes("");
    setMessage(`Created trade group #${createdGroup.id}.`);
    await loadGroups(selectedStrategy?.value ?? null);
    setSelectedGroupId(createdGroup.id);
  };

  const assignExecutions = async (executionIds: number[]) => {
    if (!selectedGroupId) {
      setError("Select a trade group before assigning executions.");
      return;
    }
    if (executionIds.length === 0) {
      setError("Select a trade with executions before assigning.");
      return;
    }

    setError(null);
    setMessage(null);

    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${selectedGroupId}/executions:assign`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_ids: executionIds,
          source: "manual",
          created_by: "ui-trader",
          reason: "manual assignment from UI",
          force_reassign: true,
        }),
      },
    );

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to assign execution"),
      );
    }

    if (executionIds.length === 1) {
      setMessage(
        `Execution ${executionIds[0]} assigned to Trade Group ${selectedGroupId}.`,
      );
    } else {
      setMessage(
        `${executionIds.length} executions assigned to Trade Group ${selectedGroupId}.`,
      );
    }
    await loadTimeline(selectedGroupId);
    await loadTrades();
  };

  const unassignExecutions = async (executionIds: number[]) => {
    if (!selectedGroupId) {
      setError("Select a trade group before unassigning executions.");
      return;
    }
    if (executionIds.length === 0) {
      setError("Select a trade with executions before unassigning.");
      return;
    }

    setError(null);
    setMessage(null);

    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${selectedGroupId}/executions:unassign`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          execution_ids: executionIds,
          source: "manual",
          created_by: "ui-trader",
          reason: "manual unassignment from UI",
        }),
      },
    );

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to unassign executions"),
      );
    }

    if (executionIds.length === 1) {
      setMessage(
        `Execution ${executionIds[0]} unassigned from Trade Group ${selectedGroupId}.`,
      );
    } else {
      setMessage(
        `${executionIds.length} executions unassigned from Trade Group ${selectedGroupId}.`,
      );
    }
    await loadTimeline(selectedGroupId);
    await loadTrades();
  };

  const toggleTradeExecutionsAssignment = async (trade: Trade) => {
    if (!selectedGroup) {
      setError("Select a trade group first.");
      return;
    }
    const tradeExecutions = await fetchTradeExecutions(trade.id);
    const executionIds = tradeExecutions.map((execution) => execution.id);
    if (trade.is_assigned) {
      await unassignExecutions(executionIds);
      return;
    }
    await assignExecutions(executionIds);
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Trade Tagging</h2>
        <p className="text-xs text-gray-500">
          Hierarchical browsing: select a strategy, then a trade group, then
          assign executions.
        </p>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading workspace...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-700">{message}</p>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(220px,20%)_minmax(360px,35%)_minmax(420px,45%)]">
        <section className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Strategies</h3>
          </div>

          <div className="mb-3 flex gap-2">
            <input
              value={newStrategyValue}
              onChange={(event) => setNewStrategyValue(event.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="New strategy"
            />
            <button
              onClick={() => {
                void createStrategy().catch((catalogError: unknown) => {
                  const nextMessage =
                    catalogError instanceof Error
                      ? catalogError.message
                      : "Failed to create strategy.";
                  setError(nextMessage);
                });
              }}
              className="whitespace-nowrap rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50"
            >
              + New Strategy
            </button>
          </div>

          <ul className="h-[380px] space-y-1 overflow-y-auto pr-1">
            {strategies.map((strategy) => (
              <li key={strategy.id}>
                <button
                  type="button"
                  className={`w-full rounded border px-2 py-2 text-left text-sm ${
                    selectedStrategyId === strategy.id
                      ? "border-blue-300 bg-blue-50 text-blue-900"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}
                  onClick={() => setSelectedStrategyId(strategy.id)}
                >
                  <p className="font-medium">{strategy.value}</p>
                </button>
              </li>
            ))}
            {strategies.length === 0 && (
              <li className="rounded border border-dashed border-gray-300 px-2 py-3 text-xs text-gray-500">
                No strategies yet.
              </li>
            )}
          </ul>
        </section>

        <section className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-2">
            <h3 className="text-sm font-semibold">Trade Groups</h3>
          </div>

          <div className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-[160px_1fr_auto]">
            <div className="rounded border border-gray-300 bg-gray-50 px-2 py-1 text-sm text-gray-700">
              {selectedStrategy ? selectedStrategy.value : "Select strategy"}
            </div>
            <input
              value={newGroupName}
              onChange={(event) => setNewGroupName(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="New trade group"
              disabled={!selectedStrategy}
            />
            <button
              onClick={() => {
                void createGroup().catch((groupError: unknown) => {
                  const nextMessage =
                    groupError instanceof Error
                      ? groupError.message
                      : "Failed to create trade group.";
                  setError(nextMessage);
                });
              }}
              disabled={!selectedStrategy}
              className="whitespace-nowrap rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              + New Trade Group
            </button>
            <textarea
              value={newGroupNotes}
              onChange={(event) => setNewGroupNotes(event.target.value)}
              className="md:col-span-3 rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="Optional notes"
              rows={2}
              disabled={!selectedStrategy}
            />
          </div>

          <ul className="h-[380px] space-y-1 overflow-y-auto pr-1">
            {loadingGroups && (
              <li className="text-xs text-gray-500">Loading trade groups...</li>
            )}
            {!loadingGroups &&
              groups.map((group) => (
                <li key={group.id}>
                  <button
                    type="button"
                    className={`w-full rounded border px-2 py-2 text-left ${
                      selectedGroupId === group.id
                        ? "border-blue-300 bg-blue-50"
                        : "border-gray-200 hover:bg-gray-50"
                    }`}
                    onClick={() => setSelectedGroupId(group.id)}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-medium text-gray-900">
                        {group.name}
                      </p>
                      <span
                        className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${statusClassName(group.status)}`}
                      >
                        {group.status}
                      </span>
                    </div>
                    <p className="mt-1 text-xs text-gray-500">
                      #{group.id} ·{" "}
                      {accountLabelById.get(group.account_id) ??
                        `Account ${group.account_id}`}{" "}
                      · Opened {formatDate(group.opened_at)}
                    </p>
                  </button>
                </li>
              ))}
            {!loadingGroups && groups.length === 0 && (
              <li className="rounded border border-dashed border-gray-300 px-2 py-3 text-xs text-gray-500">
                {selectedStrategy
                  ? "No trade groups for this strategy yet."
                  : "Select a strategy to view trade groups."}
              </li>
            )}
          </ul>
        </section>

        <section className="rounded border border-gray-200 bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">Trades</h3>
          <div className="mb-2 grid grid-cols-1 gap-2">
            <input
              value={tradeSearchQuery}
              onChange={(event) => setTradeSearchQuery(event.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="Filter trades (id, symbol, account)"
            />
          </div>
          <div className="mb-2 grid grid-cols-1 gap-2 md:grid-cols-2">
            <label className="mb-1 block text-xs text-gray-600">
              Optional Account Filter
            </label>
            <select
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
              value={tradeAccountFilter}
              onChange={(event) => setTradeAccountFilter(event.target.value)}
            >
              <option value="all">All accounts</option>
              {accounts.map((account) => (
                <option key={account.id} value={String(account.id)}>
                  {accountLabel(account)}
                </option>
              ))}
            </select>
            <label className="mb-1 block text-xs text-gray-600">
              Assignment Filter
            </label>
            <select
              className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
              value={tradeAssignmentFilter}
              onChange={(event) =>
                setTradeAssignmentFilter(
                  event.target.value as "all" | "assigned" | "unassigned",
                )
              }
            >
              <option value="all">All</option>
              <option value="assigned">Assigned</option>
              <option value="unassigned">Unassigned</option>
            </select>
          </div>

          <div className="mb-3 max-h-[220px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-600">
                  <th className="py-1 pr-2">Trade</th>
                  <th className="py-1 pr-2">Contract</th>
                  <th className="py-1 pr-2">Account</th>
                  <th className="py-1 pr-2">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredTrades.map((trade) => (
                  <tr
                    key={trade.id}
                    className={`cursor-pointer border-b border-gray-100 ${
                      selectedTradeId === trade.id
                        ? "bg-blue-50"
                        : "hover:bg-gray-50"
                    }`}
                    onClick={() => setSelectedTradeId(trade.id)}
                  >
                    <td className="py-1 pr-2 text-xs">#{trade.id}</td>
                    <td className="py-1 pr-2">
                      {trade.contract_display_name ?? trade.symbol ?? "-"}
                    </td>
                    <td className="py-1 pr-2 text-xs text-gray-600">
                      {accountLabelById.get(trade.account_id) ??
                        `Account ${trade.account_id}`}
                    </td>
                    <td className="py-1 pr-2">
                      <button
                        type="button"
                        onClick={(event) => {
                          event.stopPropagation();
                          void toggleTradeExecutionsAssignment(trade).catch(
                            (assignError: unknown) => {
                              const nextMessage =
                                assignError instanceof Error
                                  ? assignError.message
                                  : "Assignment failed.";
                              setError(nextMessage);
                            },
                          );
                        }}
                        disabled={!selectedGroup}
                        className={`rounded border px-2 py-0.5 text-[11px] font-semibold uppercase disabled:cursor-not-allowed disabled:opacity-50 ${
                          trade.is_assigned
                            ? "border-amber-300 text-amber-800 hover:bg-amber-50"
                            : "border-emerald-300 text-emerald-700 hover:bg-emerald-50"
                        }`}
                      >
                        {trade.is_assigned
                          ? `Unassign from #${selectedGroup?.id ?? "group"}`
                          : `Assign to #${selectedGroup?.id ?? "group"}`}
                      </button>
                    </td>
                  </tr>
                ))}
                {filteredTrades.length === 0 && (
                  <tr>
                    <td className="py-2 text-xs text-gray-500" colSpan={4}>
                      No trades match current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-600">
            Executions {selectedTradeId ? `for Trade #${selectedTradeId}` : ""}
          </h4>
          <div className="max-h-[210px] overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-600">
                  <th className="py-1 pr-2">Execution</th>
                  <th className="py-1 pr-2">Contract</th>
                  <th className="py-1 pr-2">Side</th>
                  <th className="py-1 pr-2">Qty</th>
                  <th className="py-1 pr-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((execution) => (
                  <tr key={execution.id} className="border-b border-gray-100">
                    <td className="py-1 pr-2 text-xs">#{execution.id}</td>
                    <td className="py-1 pr-2">
                      {execution.contract_display ?? "-"}
                    </td>
                    <td className="py-1 pr-2">{execution.side ?? "-"}</td>
                    <td className="py-1 pr-2">{execution.quantity}</td>
                    <td className="py-1 pr-2">
                      <button
                        disabled={!selectedGroup}
                        onClick={() => {
                          void assignExecutions([execution.id]).catch(
                            (assignError: unknown) => {
                              const nextMessage =
                                assignError instanceof Error
                                  ? assignError.message
                                  : "Assignment failed.";
                              setError(nextMessage);
                            },
                          );
                        }}
                        className="rounded border border-emerald-300 px-2 py-0.5 text-xs text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        Assign to{" "}
                        {selectedGroup ? `#${selectedGroup.id}` : "group"}
                      </button>
                    </td>
                  </tr>
                ))}
                {executions.length === 0 && (
                  <tr>
                    <td className="py-2 text-xs text-gray-500" colSpan={5}>
                      Select a trade to load executions.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* Timeline panel hidden for now. */}
    </div>
  );
}
