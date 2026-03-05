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

const GROUP_STATUSES: TradeGroup["status"][] = ["open", "closed", "archived"];

export default function TradeTaggingPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [strategies, setStrategies] = useState<Tag[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(
    null,
  );

  const [groups, setGroups] = useState<TradeGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [groupDetail, setGroupDetail] = useState<TradeGroupDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);

  const [showNewStrategy, setShowNewStrategy] = useState(false);
  const [newStrategyValue, setNewStrategyValue] = useState("");
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

  useEffect(() => {
    let active = true;

    Promise.all([loadStrategies(), loadAccounts()])
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
  }, [loadAccounts, loadStrategies]);

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
      setTimeline([]);
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
    void loadTimeline(selectedGroupId).catch((timelineError: unknown) => {
      const nextMessage =
        timelineError instanceof Error
          ? timelineError.message
          : "Failed to load trade group timeline.";
      setError(nextMessage);
    });
  }, [loadGroupDetail, loadTimeline, selectedGroupId]);

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
        account_id: 1,
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

  const timelineEventIcon = (eventType: string): string => {
    if (eventType.includes("entry")) return "IN";
    if (eventType.includes("exit")) return "OUT";
    if (eventType.includes("reassigned_in")) return "RE+";
    if (eventType.includes("reassigned_out")) return "RE-";
    if (eventType.includes("unassigned")) return "UN";
    if (eventType.includes("roll")) return "ROLL";
    return "ADJ";
  };

  const timelineEventColor = (eventType: string): string => {
    if (eventType.includes("entry")) return "text-emerald-700 bg-emerald-50";
    if (eventType.includes("exit")) return "text-red-700 bg-red-50";
    if (eventType.includes("unassigned")) return "text-amber-700 bg-amber-50";
    if (eventType.includes("roll")) return "text-purple-700 bg-purple-50";
    return "text-gray-700 bg-gray-50";
  };

  return (
    <div className="space-y-4">
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

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(220px,25%)_1fr]">
        {/* Column 1: Strategies */}
        <section className="rounded border border-gray-200 bg-white p-3">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold">Strategies</h3>
            <button
              onClick={() => setShowNewStrategy(!showNewStrategy)}
              className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
            >
              {showNewStrategy ? "Cancel" : "+ New"}
            </button>
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

          <ul
            className="space-y-1 overflow-y-auto pr-1"
            style={{ maxHeight: "calc(100vh - 280px)" }}
          >
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

        {/* Column 2: Trade Groups + Detail */}
        <section className="rounded border border-gray-200 bg-white p-3">
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

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(280px,35%)_1fr]">
            {/* Group list */}
            <div>
              <ul
                className="space-y-1 overflow-y-auto pr-1"
                style={{ maxHeight: "calc(100vh - 300px)" }}
              >
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
            <div>
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

                  {/* Timeline */}
                  <div>
                    <h5 className="mb-2 text-xs font-semibold uppercase tracking-wide text-gray-600">
                      Timeline ({timeline.length} events)
                    </h5>
                    {timeline.length === 0 && (
                      <p className="text-xs text-gray-400">
                        No events recorded yet.
                      </p>
                    )}
                    <div className="max-h-[300px] space-y-1 overflow-y-auto">
                      {timeline.map((event) => (
                        <div
                          key={event.event_id}
                          className="flex items-start gap-2 rounded px-2 py-1 text-xs"
                        >
                          <span
                            className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-mono text-[10px] font-bold ${timelineEventColor(event.event_type)}`}
                          >
                            {timelineEventIcon(event.event_type)}
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="text-gray-700">{event.summary}</p>
                            <p className="text-gray-400">
                              {formatDate(event.occurred_at)}
                            </p>
                          </div>
                        </div>
                      ))}
                    </div>
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
