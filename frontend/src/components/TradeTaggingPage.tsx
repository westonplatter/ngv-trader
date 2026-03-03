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
  symbol: string | null;
  status: string;
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
};

type TimelineEvent = {
  event_id: string;
  event_type: string;
  occurred_at: string;
  execution_id: number | null;
  related_trade_group_id: number | null;
  summary: string;
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "—";
  return new Date(parsed).toLocaleString();
}

export default function TradeTaggingPage() {
  const [groups, setGroups] = useState<TradeGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [selectedTradeId, setSelectedTradeId] = useState<number | null>(null);
  const [executions, setExecutions] = useState<TradeExecution[]>([]);

  const [newGroupAccountId, setNewGroupAccountId] = useState("1");
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupNotes, setNewGroupNotes] = useState("");

  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );

  const loadGroups = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/trade-groups?limit=200`);
    if (!response.ok) throw new Error(`Unable to load groups (${response.status})`);
    const data: TradeGroup[] = await response.json();
    setGroups(data);
    if (!selectedGroupId && data.length > 0) {
      setSelectedGroupId(data[0].id);
    }
  }, [selectedGroupId]);

  const loadTrades = useCallback(async () => {
    const response = await fetch(`${API_BASE_URL}/trades?limit=100`);
    if (!response.ok) throw new Error(`Unable to load trades (${response.status})`);
    const data: Trade[] = await response.json();
    setTrades(data);
  }, []);

  const loadTimeline = useCallback(async (tradeGroupId: number) => {
    const response = await fetch(`${API_BASE_URL}/trade-groups/${tradeGroupId}/timeline`);
    if (!response.ok) throw new Error(`Unable to load timeline (${response.status})`);
    const data: { events: TimelineEvent[] } = await response.json();
    setTimeline(data.events);
  }, []);

  const loadExecutions = useCallback(async (tradeId: number) => {
    const response = await fetch(`${API_BASE_URL}/trades/${tradeId}/executions`);
    if (!response.ok) throw new Error(`Unable to load executions (${response.status})`);
    const data: TradeExecution[] = await response.json();
    setExecutions(data);
  }, []);

  useEffect(() => {
    let active = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    Promise.all([loadGroups(), loadTrades()])
      .catch((loadError: unknown) => {
        if (!active) return;
        const nextMessage =
          loadError instanceof Error ? loadError.message : "Failed to load tagging workspace.";
        setError(nextMessage);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [loadGroups, loadTrades]);

  useEffect(() => {
    if (selectedGroupId == null) {
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
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
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadExecutions(selectedTradeId).catch((executionError: unknown) => {
      const nextMessage =
        executionError instanceof Error ? executionError.message : "Failed to load executions.";
      setError(nextMessage);
    });
  }, [loadExecutions, selectedTradeId]);

  const createGroup = async () => {
    if (!newGroupName.trim()) {
      setError("Group name is required.");
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
        source: "manual",
        created_by: "ui-trader",
      }),
    });

    if (!response.ok) {
      throw new Error(`Unable to create group (${response.status})`);
    }

    const createdGroup: TradeGroup = await response.json();
    setMessage(`Created trade group #${createdGroup.id}.`);
    setNewGroupName("");
    setNewGroupNotes("");
    await loadGroups();
    setSelectedGroupId(createdGroup.id);
  };

  const assignExecution = async (executionId: number) => {
    if (!selectedGroupId) {
      setError("Select a trade group before assigning executions.");
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
          execution_ids: [executionId],
          source: "manual",
          created_by: "ui-trader",
          reason: "manual assignment from UI",
          force_reassign: true,
        }),
      },
    );

    if (!response.ok) {
      throw new Error(`Unable to assign execution (${response.status})`);
    }

    setMessage(`Execution ${executionId} assigned to Trade Group ${selectedGroupId}.`);
    await loadTimeline(selectedGroupId);
  };

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Trade Tagging</h2>
        <p className="text-xs text-gray-500">
          Create lifecycle groups and manually assign executions from recent trades.
        </p>
      </div>

      {loading && <p className="text-sm text-gray-600">Loading workspace…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}
      {message && <p className="text-sm text-green-700">{message}</p>}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className="rounded border border-gray-200 bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">Create Trade Group</h3>
          <div className="space-y-2">
            <label className="block text-xs text-gray-600">
              Account ID
              <input
                value={newGroupAccountId}
                onChange={(event) => setNewGroupAccountId(event.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="block text-xs text-gray-600">
              Name
              <input
                value={newGroupName}
                onChange={(event) => setNewGroupName(event.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder="CL Calendar Roll Campaign"
              />
            </label>
            <label className="block text-xs text-gray-600">
              Notes
              <textarea
                value={newGroupNotes}
                onChange={(event) => setNewGroupNotes(event.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-2 py-1 text-sm"
                rows={3}
                placeholder="Operator notes"
              />
            </label>
            <button
              onClick={() => {
                void createGroup().catch((createError: unknown) => {
                  const nextMessage =
                    createError instanceof Error
                      ? createError.message
                      : "Failed to create trade group.";
                  setError(nextMessage);
                });
              }}
              className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50"
            >
              Create Group
            </button>
          </div>
        </div>

        <div className="rounded border border-gray-200 bg-white p-3 xl:col-span-2">
          <h3 className="mb-2 text-sm font-semibold">Trade Groups</h3>
          <div className="max-h-64 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-600">
                  <th className="py-1 pr-2">ID</th>
                  <th className="py-1 pr-2">Name</th>
                  <th className="py-1 pr-2">Status</th>
                  <th className="py-1 pr-2">Opened</th>
                </tr>
              </thead>
              <tbody>
                {groups.map((group) => (
                  <tr
                    key={group.id}
                    className={`cursor-pointer border-b border-gray-100 ${
                      selectedGroupId === group.id ? "bg-blue-50" : "hover:bg-gray-50"
                    }`}
                    onClick={() => setSelectedGroupId(group.id)}
                  >
                    <td className="py-1 pr-2 font-mono text-xs">#{group.id}</td>
                    <td className="py-1 pr-2">{group.name}</td>
                    <td className="py-1 pr-2">{group.status}</td>
                    <td className="py-1 pr-2 text-xs text-gray-600">
                      {formatDate(group.opened_at)}
                    </td>
                  </tr>
                ))}
                {groups.length === 0 && (
                  <tr>
                    <td className="py-2 text-xs text-gray-500" colSpan={4}>
                      No trade groups yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded border border-gray-200 bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">Recent Trades → Assign Executions</h3>
          <select
            className="mb-2 w-full rounded border border-gray-300 px-2 py-1 text-sm"
            value={selectedTradeId ?? ""}
            onChange={(event) => {
              const nextValue = Number(event.target.value);
              setSelectedTradeId(Number.isNaN(nextValue) ? null : nextValue);
            }}
          >
            <option value="">Select trade</option>
            {trades.map((trade) => (
              <option key={trade.id} value={trade.id}>
                #{trade.id} · acct {trade.account_id} · {trade.symbol ?? "—"} · {trade.status}
              </option>
            ))}
          </select>

          <div className="max-h-72 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-600">
                  <th className="py-1 pr-2">Execution</th>
                  <th className="py-1 pr-2">Side</th>
                  <th className="py-1 pr-2">Qty</th>
                  <th className="py-1 pr-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((execution) => (
                  <tr key={execution.id} className="border-b border-gray-100">
                    <td className="py-1 pr-2 text-xs">#{execution.id}</td>
                    <td className="py-1 pr-2">{execution.side ?? "—"}</td>
                    <td className="py-1 pr-2">{execution.quantity}</td>
                    <td className="py-1 pr-2">
                      <button
                        disabled={!selectedGroup}
                        onClick={() => {
                          void assignExecution(execution.id).catch(
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
                        Assign to {selectedGroup ? `#${selectedGroup.id}` : "group"}
                      </button>
                    </td>
                  </tr>
                ))}
                {executions.length === 0 && (
                  <tr>
                    <td className="py-2 text-xs text-gray-500" colSpan={4}>
                      Select a trade to load executions.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded border border-gray-200 bg-white p-3">
          <h3 className="mb-2 text-sm font-semibold">
            {selectedGroup ? `Timeline · Trade Group #${selectedGroup.id}` : "Timeline"}
          </h3>
          <div className="max-h-72 overflow-auto">
            <ul className="space-y-1">
              {timeline.map((event) => (
                <li key={event.event_id} className="rounded border border-gray-100 px-2 py-1">
                  <p className="text-xs font-medium text-gray-900">{event.event_type}</p>
                  <p className="text-xs text-gray-700">{event.summary}</p>
                  <p className="text-[11px] text-gray-500">{formatDate(event.occurred_at)}</p>
                </li>
              ))}
              {timeline.length === 0 && (
                <li className="text-xs text-gray-500">Select a trade group to load timeline events.</li>
              )}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}
