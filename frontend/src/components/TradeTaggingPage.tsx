import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE_URL } from "../config";

type TradeGroup = {
  id: number;
  account_id: number | null;
  name: string;
  notes: string | null;
  status: "open" | "closed" | "archived";
  opened_at: string;
  closed_at: string | null;
  opened_by: string | null;
  closed_by: string | null;
};

type TradeGroupDetail = TradeGroup & {
  tags: TagLink[];
  execution_count: number;
};

type TagLink = {
  id: number;
  entity_type: string;
  entity_id: number;
  tag_id: number;
  tag_type: string;
  is_primary: boolean;
  source: string;
  created_by: string;
};

type GroupExecution = {
  id: number;
  trade_id: number;
  account_id: number;
  account_alias: string | null;
  executed_at: string;
  side: string | null;
  quantity: number;
  price: number;
  commission: number | null;
  realized_pnl: number | null;
  exec_role: string;
  sec_type: string | null;
  contract_display: string | null;
  data_source: string;
};

type GroupOpenPosition = {
  account_id: number;
  account_alias: string | null;
  con_id: number;
  symbol: string | null;
  local_symbol: string | null;
  contract_display: string | null;
  sec_type: string | null;
  position: number;
  avg_cost: number;
  multiplier: string | null;
  mark_price: number | null;
  position_value: number | null;
  fifo_pnl_unrealized: number | null;
  as_of_date: string | null;
};

type GroupExecutionsResponse = {
  trade_group_id: number;
  total_realized_pnl: number | null;
  total_unrealized_pnl: number | null;
  executions: GroupExecution[];
  open_positions: GroupOpenPosition[];
};

type Tag = {
  id: number;
  tag_type: string;
  value: string;
  normalized_value: string;
  created_by: string;
  created_at: string;
  archived_at: string | null;
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

const GROUP_STATUSES: TradeGroup["status"][] = ["open", "closed", "archived"];

export default function TradeTaggingPage() {
  const [strategies, setStrategies] = useState<Tag[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(
    null,
  );

  const [groups, setGroups] = useState<TradeGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [groupDetail, setGroupDetail] = useState<TradeGroupDetail | null>(null);
  const [executions, setExecutions] = useState<GroupExecution[]>([]);
  const [totalRealizedPnl, setTotalRealizedPnl] = useState<number | null>(null);
  const [openPositions, setOpenPositions] = useState<GroupOpenPosition[]>([]);
  const [totalUnrealizedPnl, setTotalUnrealizedPnl] = useState<number | null>(
    null,
  );

  const [showNewStrategy, setShowNewStrategy] = useState(false);
  const [newStrategyValue, setNewStrategyValue] = useState("");
  const [showArchivedStrategies, setShowArchivedStrategies] = useState(false);
  const [showNewGroup, setShowNewGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupNotes, setNewGroupNotes] = useState("");

  const [editingGroup, setEditingGroup] = useState(false);
  const [editName, setEditName] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editStatus, setEditStatus] = useState<TradeGroup["status"]>("open");

  const [loading, setLoading] = useState(true);
  const [loadingGroups, setLoadingGroups] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedStrategy = useMemo(
    () =>
      strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [selectedStrategyId, strategies],
  );

  const loadStrategies = useCallback(async () => {
    const params = new URLSearchParams({ limit: "200" });
    if (showArchivedStrategies) params.set("include_archived", "true");
    const response = await fetch(
      `${API_BASE_URL}/strategies?${params.toString()}`,
    );
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
  }, [showArchivedStrategies]);

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

  const loadGroupDetail = useCallback(async (groupId: number) => {
    const response = await fetch(`${API_BASE_URL}/trade-groups/${groupId}`);
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load group detail"),
      );
    }
    const data: TradeGroupDetail = await response.json();
    setGroupDetail(data);
  }, []);

  const loadExecutions = useCallback(async (tradeGroupId: number) => {
    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${tradeGroupId}/executions`,
    );
    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to load group executions"),
      );
    }
    const data: GroupExecutionsResponse = await response.json();
    setExecutions(data.executions);
    setTotalRealizedPnl(data.total_realized_pnl);
    setOpenPositions(data.open_positions ?? []);
    setTotalUnrealizedPnl(data.total_unrealized_pnl);
  }, []);

  useEffect(() => {
    let active = true;

    loadStrategies()
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
  }, [loadStrategies]);

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
      setGroupDetail(null);
      setExecutions([]);
      setTotalRealizedPnl(null);
      setOpenPositions([]);
      setTotalUnrealizedPnl(null);
      setEditingGroup(false);
      return;
    }

    void loadGroupDetail(selectedGroupId).catch((detailError: unknown) => {
      const nextMessage =
        detailError instanceof Error
          ? detailError.message
          : "Failed to load group detail.";
      setError(nextMessage);
    });
    void loadExecutions(selectedGroupId).catch((execError: unknown) => {
      const nextMessage =
        execError instanceof Error
          ? execError.message
          : "Failed to load trade group executions.";
      setError(nextMessage);
    });
  }, [loadGroupDetail, loadExecutions, selectedGroupId]);

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
    setShowNewStrategy(false);
    setMessage("Created strategy.");
    await loadStrategies();
    setSelectedStrategyId(createdStrategy.id);
  };

  const setStrategyArchived = async (strategy: Tag, archived: boolean) => {
    setError(null);
    setMessage(null);

    const action = archived ? "archive" : "unarchive";
    const response = await fetch(
      `${API_BASE_URL}/strategies/${strategy.id}/${action}`,
      { method: "POST" },
    );

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, `Unable to ${action} strategy`),
      );
    }

    setMessage(archived ? "Archived strategy." : "Unarchived strategy.");
    await loadStrategies();
  };

  const createGroup = async () => {
    if (!selectedStrategyId) {
      setError("Select a strategy before creating a trade group.");
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
    setShowNewGroup(false);
    setMessage(`Created trade group #${createdGroup.id}.`);
    await loadGroups(selectedStrategy?.value ?? null);
    setSelectedGroupId(createdGroup.id);
  };

  const saveGroupEdits = async () => {
    if (!selectedGroupId) return;

    setError(null);
    setMessage(null);

    const body: Record<string, string | null> = {};
    if (editName.trim() !== (groupDetail?.name ?? "")) {
      body.name = editName.trim();
    }
    if (editNotes !== (groupDetail?.notes ?? "")) {
      body.notes = editNotes || null;
    }
    if (editStatus !== groupDetail?.status) {
      body.status = editStatus;
      if (editStatus === "closed") {
        body.closed_by = "ui-trader";
        body.closed_at = new Date().toISOString();
      }
    }

    if (Object.keys(body).length === 0) {
      setEditingGroup(false);
      return;
    }

    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${selectedGroupId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );

    if (!response.ok) {
      throw new Error(
        await readErrorMessage(response, "Unable to update trade group"),
      );
    }

    setMessage("Trade group updated.");
    setEditingGroup(false);
    await loadGroups(selectedStrategy?.value ?? null);
    await loadGroupDetail(selectedGroupId);
  };

  const startEditing = () => {
    if (!groupDetail) return;
    setEditName(groupDetail.name);
    setEditNotes(groupDetail.notes ?? "");
    setEditStatus(groupDetail.status);
    setEditingGroup(true);
  };

  const deleteGroup = async () => {
    if (!selectedGroupId) return;
    if (
      !window.confirm(
        `Delete trade group #${selectedGroupId}? This will unassign all executions.`,
      )
    )
      return;

    setError(null);
    setMessage(null);

    const response = await fetch(
      `${API_BASE_URL}/trade-groups/${selectedGroupId}?source=manual&created_by=ui-trader&reason=deleted+from+tagging+page`,
      { method: "DELETE" },
    );

    if (!response.ok && response.status !== 204) {
      throw new Error(
        await readErrorMessage(response, "Unable to delete trade group"),
      );
    }

    setMessage(`Deleted trade group #${selectedGroupId}.`);
    setSelectedGroupId(null);
    await loadGroups(selectedStrategy?.value ?? null);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Trade Tagging</h2>
        <p className="text-xs text-gray-500">
          Manage strategies and trade groups. Assign trades from the{" "}
          <a
            href="/trades"
            className="text-blue-600 underline hover:text-blue-800"
          >
            Trades
          </a>{" "}
          page.
        </p>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading workspace...</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-700">{message}</p>}

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,25%)_1fr]">
        {/* Column 1: Strategies */}
        <section className="flex min-h-0 flex-col rounded border border-gray-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Strategies</h3>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-1 text-xs text-gray-500">
                <input
                  type="checkbox"
                  checked={showArchivedStrategies}
                  onChange={(event) =>
                    setShowArchivedStrategies(event.target.checked)
                  }
                />
                Show archived
              </label>
              <button
                onClick={() => setShowNewStrategy(!showNewStrategy)}
                className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
              >
                {showNewStrategy ? "Cancel" : "+ New"}
              </button>
            </div>
          </div>

          {showNewStrategy && (
            <div className="mb-3 space-y-2 rounded border border-dashed border-gray-300 p-2">
              <input
                value={newStrategyValue}
                onChange={(event) => setNewStrategyValue(event.target.value)}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder="Strategy name"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    void createStrategy().catch((err: unknown) => {
                      setError(
                        err instanceof Error
                          ? err.message
                          : "Failed to create strategy.",
                      );
                    });
                  }
                }}
              />
              <button
                onClick={() => {
                  void createStrategy().catch((err: unknown) => {
                    setError(
                      err instanceof Error
                        ? err.message
                        : "Failed to create strategy.",
                    );
                  });
                }}
                className="w-full rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50"
              >
                Create Strategy
              </button>
            </div>
          )}

          <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {strategies.map((strategy) => {
              const isArchived = strategy.archived_at !== null;
              return (
                <li key={strategy.id} className="group relative">
                  <button
                    type="button"
                    className={`w-full rounded border px-2 py-2 pr-16 text-left text-sm ${
                      selectedStrategyId === strategy.id
                        ? "border-blue-300 bg-blue-50 text-blue-900"
                        : "border-gray-200 hover:bg-gray-50"
                    } ${isArchived ? "opacity-60" : ""}`}
                    onClick={() => setSelectedStrategyId(strategy.id)}
                  >
                    <p className="font-medium">
                      {strategy.value}
                      {isArchived && (
                        <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-normal text-amber-800">
                          Archived
                        </span>
                      )}
                    </p>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void setStrategyArchived(strategy, !isArchived).catch(
                        (err: unknown) => {
                          setError(
                            err instanceof Error
                              ? err.message
                              : "Failed to update strategy.",
                          );
                        },
                      );
                    }}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded border border-gray-200 bg-white px-1.5 py-0.5 text-[10px] text-gray-500 opacity-0 hover:bg-gray-50 group-hover:opacity-100"
                  >
                    {isArchived ? "Unarchive" : "Archive"}
                  </button>
                </li>
              );
            })}
            {strategies.length === 0 && (
              <li className="rounded border border-dashed border-gray-300 px-2 py-3 text-xs text-gray-500">
                No strategies yet.
              </li>
            )}
          </ul>
        </section>

        {/* Column 2: Trade Groups + Detail */}
        <section className="flex min-h-0 flex-col rounded border border-gray-200 bg-white p-3">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold">
              Trade Groups
              {selectedStrategy && (
                <span className="ml-1 font-normal text-gray-500">
                  ({selectedStrategy.value})
                </span>
              )}
            </h3>
            <button
              onClick={() => setShowNewGroup(!showNewGroup)}
              disabled={!selectedStrategy}
              className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {showNewGroup ? "Cancel" : "+ New"}
            </button>
          </div>

          {showNewGroup && selectedStrategy && (
            <div className="mb-3 space-y-2 rounded border border-dashed border-gray-300 p-2">
              <div className="flex items-center gap-2">
                <span className="shrink-0 rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">
                  {selectedStrategy.value}
                </span>
                <input
                  value={newGroupName}
                  onChange={(event) => setNewGroupName(event.target.value)}
                  className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
                  placeholder="Trade group name"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      void createGroup().catch((err: unknown) => {
                        setError(
                          err instanceof Error
                            ? err.message
                            : "Failed to create trade group.",
                        );
                      });
                    }
                  }}
                />
              </div>
              <textarea
                value={newGroupNotes}
                onChange={(event) => setNewGroupNotes(event.target.value)}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder="Optional notes"
                rows={1}
              />
              <button
                onClick={() => {
                  void createGroup().catch((err: unknown) => {
                    setError(
                      err instanceof Error
                        ? err.message
                        : "Failed to create trade group.",
                    );
                  });
                }}
                className="w-full rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50"
              >
                Create Trade Group
              </button>
            </div>
          )}

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(280px,35%)_1fr]">
            {/* Group list */}
            <div className="flex min-h-0 flex-col">
              <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
                {loadingGroups && (
                  <li className="text-xs text-gray-500">
                    Loading trade groups...
                  </li>
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
                          #{group.id} · Opened {formatDate(group.opened_at)}
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
            </div>

            {/* Group detail */}
            <div className="min-h-0 overflow-y-auto">
              {!groupDetail && selectedGroupId == null && (
                <div className="flex h-full items-center justify-center text-sm text-gray-400">
                  Select a trade group to view details.
                </div>
              )}

              {groupDetail && !editingGroup && (
                <div className="space-y-4">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-base font-semibold text-gray-900">
                        {groupDetail.name}
                      </h4>
                      <p className="text-xs text-gray-500">#{groupDetail.id}</p>
                    </div>
                    <div className="flex items-center gap-1">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${statusClassName(groupDetail.status)}`}
                      >
                        {groupDetail.status}
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                    <div>
                      <span className="text-xs text-gray-500">Opened</span>
                      <p className="text-gray-800">
                        {formatDate(groupDetail.opened_at)}
                      </p>
                    </div>
                    <div>
                      <span className="text-xs text-gray-500">Closed</span>
                      <p className="text-gray-800">
                        {formatDate(groupDetail.closed_at)}
                      </p>
                    </div>
                    <div>
                      <span className="text-xs text-gray-500">Executions</span>
                      <p className="text-gray-800">
                        {groupDetail.execution_count}
                      </p>
                    </div>
                    <div>
                      <span className="text-xs text-gray-500">Tags</span>
                      <p className="text-gray-800">
                        {groupDetail.tags.length === 0
                          ? "None"
                          : groupDetail.tags.map((t) => t.tag_type).join(", ")}
                      </p>
                    </div>
                  </div>

                  {groupDetail.notes && (
                    <div>
                      <span className="text-xs text-gray-500">Notes</span>
                      <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-700">
                        {groupDetail.notes}
                      </p>
                    </div>
                  )}

                  <div className="flex gap-2">
                    <button
                      onClick={startEditing}
                      className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-700 hover:bg-gray-50"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => {
                        void deleteGroup().catch((err: unknown) => {
                          setError(
                            err instanceof Error
                              ? err.message
                              : "Failed to delete group.",
                          );
                        });
                      }}
                      className="rounded border border-red-200 px-3 py-1 text-xs text-red-600 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>

                  {/* PnL Summary */}
                  {(() => {
                    const totalPnl =
                      totalUnrealizedPnl == null && totalRealizedPnl == null
                        ? null
                        : (totalUnrealizedPnl ?? 0) + (totalRealizedPnl ?? 0);
                    let capital: number | null = null;
                    let optionsCapital: number | null = null;
                    let equityCapital: number | null = null;
                    if (openPositions.length > 0) {
                      let optionsSum = 0;
                      let equitySum = 0;
                      let allHaveMultiplier = true;
                      for (const pos of openPositions) {
                        const mult =
                          pos.multiplier != null
                            ? Number.parseFloat(pos.multiplier)
                            : NaN;
                        if (!Number.isFinite(mult) || mult <= 0) {
                          allHaveMultiplier = false;
                          break;
                        }
                        const posCapital =
                          Math.abs(pos.avg_cost * pos.position) * mult;
                        if (pos.sec_type === "OPT" || pos.sec_type === "FOP") {
                          optionsSum += posCapital;
                        } else {
                          equitySum += posCapital;
                        }
                      }
                      if (allHaveMultiplier && optionsSum + equitySum > 0) {
                        optionsCapital = optionsSum;
                        equityCapital = equitySum;
                        capital = optionsSum + equitySum;
                      }
                    }
                    const fmt = (v: number | null) =>
                      v == null
                        ? "—"
                        : v.toLocaleString(undefined, {
                            style: "currency",
                            currency: "USD",
                          });
                    const cls = (v: number | null) =>
                      v == null
                        ? "text-gray-500"
                        : v >= 0
                          ? "font-semibold text-emerald-700"
                          : "font-semibold text-red-700";
                    const pct = (v: number | null) =>
                      v == null || capital == null
                        ? "—"
                        : `${((v / capital) * 100).toFixed(2)}%`;
                    const row = (
                      label: string,
                      v: number | null,
                      showPct: boolean,
                      colorize: boolean,
                    ) => (
                      <div className="grid grid-cols-[7rem_6rem_5rem] items-baseline">
                        <span className="text-gray-500">{label}:</span>
                        <span
                          className={`text-right ${colorize ? cls(v) : "font-semibold text-gray-800"}`}
                        >
                          {fmt(v)}
                        </span>
                        <span
                          className={`text-right ${showPct ? cls(v) : "text-gray-400"}`}
                        >
                          {showPct ? pct(v) : ""}
                        </span>
                      </div>
                    );
                    const subRow = (label: string, v: number | null) => (
                      <div className="grid grid-cols-[7rem_6rem_5rem] items-baseline">
                        <span className="pl-3 text-gray-400">{label}:</span>
                        <span className="text-right font-medium text-gray-600">
                          {fmt(v)}
                        </span>
                        <span />
                      </div>
                    );
                    return (
                      <div className="flex flex-col gap-0.5 rounded border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs">
                        {row("Capital invested", capital, false, false)}
                        {subRow("Options capital", optionsCapital)}
                        {subRow("Equity capital", equityCapital)}
                        {row("Total PnL", totalPnl, true, true)}
                        {row("Unrealized PnL", totalUnrealizedPnl, true, true)}
                        {row("Realized PnL", totalRealizedPnl, true, true)}
                      </div>
                    );
                  })()}

                  {/* Open Positions */}
                  <div>
                    <div className="mb-2 flex items-baseline justify-between">
                      <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
                        Open Positions ({openPositions.length})
                      </h5>
                      <span className="text-xs text-gray-600">
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
                          {totalUnrealizedPnl == null
                            ? "—"
                            : totalUnrealizedPnl.toLocaleString(undefined, {
                                style: "currency",
                                currency: "USD",
                              })}
                        </span>
                      </span>
                    </div>
                    {openPositions.length === 0 && (
                      <p className="mb-3 text-xs text-gray-400">
                        No open positions linked to this group.
                      </p>
                    )}
                    {openPositions.length > 0 && (
                      <div className="mb-4 max-h-[260px] overflow-auto rounded border border-gray-200">
                        <table className="w-full text-left text-xs">
                          <thead className="sticky top-0 bg-gray-50 text-gray-600">
                            <tr>
                              <th className="px-2 py-1 font-medium">Account</th>
                              <th className="px-2 py-1 font-medium">
                                Contract
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Qty
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Avg Cost
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Mark
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Value
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Unrealized
                              </th>
                              <th className="px-2 py-1 font-medium">As of</th>
                            </tr>
                          </thead>
                          <tbody>
                            {openPositions.map((pos) => {
                              const qtyClass =
                                pos.position > 0
                                  ? "text-emerald-700"
                                  : pos.position < 0
                                    ? "text-red-700"
                                    : "text-gray-600";
                              const pnlClass =
                                pos.fifo_pnl_unrealized == null
                                  ? "text-gray-400"
                                  : pos.fifo_pnl_unrealized >= 0
                                    ? "text-emerald-700"
                                    : "text-red-700";
                              return (
                                <tr
                                  key={`${pos.account_id}-${pos.con_id}`}
                                  className="border-t border-gray-100"
                                >
                                  <td className="px-2 py-1 text-gray-700">
                                    {pos.account_alias ??
                                      `Account ${pos.account_id}`}
                                  </td>
                                  <td className="px-2 py-1 text-gray-800">
                                    {pos.contract_display ??
                                      pos.local_symbol ??
                                      pos.symbol ??
                                      `#${pos.con_id}`}
                                  </td>
                                  <td
                                    className={`px-2 py-1 text-right font-mono ${qtyClass}`}
                                  >
                                    {pos.position}
                                  </td>
                                  <td className="px-2 py-1 text-right font-mono text-gray-700">
                                    {pos.avg_cost.toFixed(2)}
                                  </td>
                                  <td className="px-2 py-1 text-right font-mono text-gray-700">
                                    {pos.mark_price == null
                                      ? "—"
                                      : pos.mark_price.toFixed(2)}
                                  </td>
                                  <td className="px-2 py-1 text-right font-mono text-gray-700">
                                    {pos.position_value == null
                                      ? "—"
                                      : pos.position_value.toFixed(2)}
                                  </td>
                                  <td
                                    className={`px-2 py-1 text-right font-mono ${pnlClass}`}
                                  >
                                    {pos.fifo_pnl_unrealized == null
                                      ? "—"
                                      : pos.fifo_pnl_unrealized.toFixed(2)}
                                  </td>
                                  <td className="px-2 py-1 text-gray-500">
                                    {pos.as_of_date ?? "—"}
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {/* Trades */}
                  <div>
                    <div className="mb-2 flex items-baseline justify-between">
                      <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
                        Trades ({executions.length})
                      </h5>
                      <span className="text-xs text-gray-600">
                        Total realized PnL:{" "}
                        <span
                          className={
                            totalRealizedPnl == null
                              ? "text-gray-500"
                              : totalRealizedPnl >= 0
                                ? "font-semibold text-emerald-700"
                                : "font-semibold text-red-700"
                          }
                        >
                          {totalRealizedPnl == null
                            ? "—"
                            : totalRealizedPnl.toLocaleString(undefined, {
                                style: "currency",
                                currency: "USD",
                              })}
                        </span>
                      </span>
                    </div>
                    {executions.length === 0 && (
                      <p className="mb-3 text-xs text-gray-400">
                        No trades assigned to this group yet.
                      </p>
                    )}
                    {executions.length > 0 && (
                      <div className="mb-4 max-h-[300px] overflow-auto rounded border border-gray-200">
                        <table className="w-full text-left text-xs">
                          <thead className="sticky top-0 bg-gray-50 text-gray-600">
                            <tr>
                              <th className="px-2 py-1 font-medium">When</th>
                              <th className="px-2 py-1 font-medium">Account</th>
                              <th className="px-2 py-1 font-medium">
                                Contract
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Side
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Qty
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Price
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Realized
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Cum PnL
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            {(() => {
                              let running = 0;
                              const withRunning = executions.map((ex) => {
                                const counted =
                                  ex.realized_pnl != null &&
                                  ex.exec_role !== "combo_summary";
                                if (counted)
                                  running += ex.realized_pnl as number;
                                return { ex, counted, running };
                              });
                              return [...withRunning]
                                .reverse()
                                .map(({ ex, counted, running }) => {
                                  const sideClass =
                                    ex.side && /^(BOT|BUY)$/i.test(ex.side)
                                      ? "text-emerald-700"
                                      : ex.side
                                        ? "text-red-700"
                                        : "text-gray-500";
                                  const pnlClass =
                                    ex.realized_pnl == null
                                      ? "text-gray-400"
                                      : ex.realized_pnl >= 0
                                        ? "text-emerald-700"
                                        : "text-red-700";
                                  return (
                                    <tr
                                      key={ex.id}
                                      className="border-t border-gray-100"
                                    >
                                      <td className="px-2 py-1 text-gray-700">
                                        {formatDate(ex.executed_at)}
                                      </td>
                                      <td className="px-2 py-1 text-gray-700">
                                        {ex.account_alias ??
                                          `Account ${ex.account_id}`}
                                      </td>
                                      <td className="px-2 py-1 text-gray-800">
                                        {ex.contract_display ??
                                          `#${ex.trade_id}`}
                                        {ex.exec_role !== "standalone" && (
                                          <span className="ml-1 rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase text-gray-500">
                                            {ex.exec_role}
                                          </span>
                                        )}
                                      </td>
                                      <td
                                        className={`px-2 py-1 text-right font-mono ${sideClass}`}
                                      >
                                        {ex.side ?? "—"}
                                      </td>
                                      <td className="px-2 py-1 text-right font-mono text-gray-800">
                                        {ex.quantity}
                                      </td>
                                      <td className="px-2 py-1 text-right font-mono text-gray-800">
                                        {Number(ex.price.toFixed(4))}
                                      </td>
                                      <td
                                        className={`px-2 py-1 text-right font-mono ${pnlClass}`}
                                      >
                                        {ex.realized_pnl == null
                                          ? "—"
                                          : ex.realized_pnl.toFixed(2)}
                                      </td>
                                      <td className="px-2 py-1 text-right font-mono text-gray-700">
                                        {counted ? running.toFixed(2) : "—"}
                                      </td>
                                    </tr>
                                  );
                                });
                            })()}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {groupDetail && editingGroup && (
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-900">
                    Edit Trade Group #{groupDetail.id}
                  </h4>
                  <div>
                    <label className="mb-1 block text-xs text-gray-600">
                      Name
                    </label>
                    <input
                      value={editName}
                      onChange={(e) => setEditName(e.target.value)}
                      className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-600">
                      Notes
                    </label>
                    <textarea
                      value={editNotes}
                      onChange={(e) => setEditNotes(e.target.value)}
                      className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                      rows={3}
                    />
                  </div>
                  <div>
                    <label className="mb-1 block text-xs text-gray-600">
                      Status
                    </label>
                    <div className="flex gap-2">
                      {GROUP_STATUSES.map((s) => (
                        <button
                          key={s}
                          onClick={() => setEditStatus(s)}
                          className={`rounded border px-3 py-1 text-xs font-semibold uppercase ${
                            editStatus === s
                              ? statusClassName(s) + " border-current"
                              : "border-gray-200 text-gray-500 hover:bg-gray-50"
                          }`}
                        >
                          {s}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => {
                        void saveGroupEdits().catch((err: unknown) => {
                          setError(
                            err instanceof Error
                              ? err.message
                              : "Failed to save changes.",
                          );
                        });
                      }}
                      className="rounded border border-blue-300 px-4 py-1 text-sm text-blue-700 hover:bg-blue-50"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingGroup(false)}
                      className="rounded border border-gray-300 px-4 py-1 text-sm text-gray-600 hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
