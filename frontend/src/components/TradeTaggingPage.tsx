import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { API_BASE_URL } from "../config";

export type TradeGroup = {
  id: number;
  account_id: number | null;
  name: string;
  notes: string | null;
  status: "open" | "closed" | "archived";
  primary_strategy_value: string | null;
  opened_at: string;
  closed_at: string | null;
  opened_by: string | null;
  closed_by: string | null;
};

export type TradeGroupDetail = TradeGroup & {
  tags: TagLink[];
  execution_count: number;
};

export type TagLink = {
  id: number;
  entity_type: string;
  entity_id: number;
  tag_id: number;
  tag_type: string;
  is_primary: boolean;
  source: string;
  created_by: string;
};

export type GroupExecution = {
  id: number;
  trade_id: number | null;
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
  // False for preemptively-tagged live fills not yet settled.
  settled?: boolean;
};

export type GroupOpenPosition = {
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
  // Intraday overlay (additive): live current-state fields.
  source: string;
  mark: number | null;
  mark_ts: string | null;
  live_unrealized: number | null;
};

export type GroupAccountPnl = {
  account_id: number;
  account_alias: string | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  intraday_unrealized_pnl: number | null;
  intraday_realized_pnl: number | null;
  intraday_total_pnl: number | null;
};

export type GroupExecutionsResponse = {
  trade_group_id: number;
  total_realized_pnl: number | null;
  total_unrealized_pnl: number | null;
  executions: GroupExecution[];
  open_positions: GroupOpenPosition[];
  // Intraday overlay (additive).
  intraday_unrealized_pnl: number | null;
  intraday_realized_pnl: number | null;
  intraday_total_pnl: number | null;
  marks_as_of: string | null;
  // Per-account breakdown (additive).
  by_account: GroupAccountPnl[];
};

export type Tag = {
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

function formatMarkTime(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "";
  return new Date(parsed).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
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

// Resolve which strategy owns a trade group, so a deep link that only carries
// a trade_group_id can select the right parent strategy. Returns the strategy
// tag value, or null if it can't be determined.
async function fetchGroupStrategyValue(
  groupId: number,
): Promise<string | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/trade-groups/${groupId}`);
    if (!response.ok) return null;
    const detail: TradeGroupDetail = await response.json();
    return detail.primary_strategy_value;
  } catch {
    return null;
  }
}

function statusClassName(status: TradeGroup["status"]): string {
  if (status === "open") return "bg-emerald-100 text-emerald-800";
  if (status === "closed") return "bg-gray-100 text-gray-700";
  return "bg-amber-100 text-amber-800";
}

const GROUP_STATUSES: TradeGroup["status"][] = ["open", "closed", "archived"];

type GroupFilter = "active" | "closed" | "archived" | "all";

const GROUP_FILTERS: { value: GroupFilter; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "closed", label: "Closed" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

type GroupSort = "name" | "opened_at";

const GROUP_SORTS: { value: GroupSort; label: string }[] = [
  { value: "name", label: "A–Z" },
  { value: "opened_at", label: "Opened" },
];

function parseIdParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function TradeTaggingPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [strategies, setStrategies] = useState<Tag[]>([]);
  const [selectedStrategyId, setSelectedStrategyId] = useState<number | null>(
    () => parseIdParam(searchParams.get("strategy_id")),
  );

  const [groups, setGroups] = useState<TradeGroup[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(() =>
    parseIdParam(searchParams.get("trade_group_id")),
  );

  // Captured once at mount. Used to resolve the parent strategy for a trade
  // group deep link (?trade_group_id=N) exactly once, without re-running when
  // the URL is later kept in sync with the current selection.
  const initialGroupIdRef = useRef(
    parseIdParam(searchParams.get("trade_group_id")),
  );
  const initialStrategyIdRef = useRef(
    parseIdParam(searchParams.get("strategy_id")),
  );
  const deepLinkResolvedRef = useRef(false);
  const [groupDetail, setGroupDetail] = useState<TradeGroupDetail | null>(null);
  const [executions, setExecutions] = useState<GroupExecution[]>([]);
  const [totalRealizedPnl, setTotalRealizedPnl] = useState<number | null>(null);
  const [openPositions, setOpenPositions] = useState<GroupOpenPosition[]>([]);
  const [totalUnrealizedPnl, setTotalUnrealizedPnl] = useState<number | null>(
    null,
  );
  const [intradayUnrealizedPnl, setIntradayUnrealizedPnl] = useState<
    number | null
  >(null);
  const [intradayRealizedPnl, setIntradayRealizedPnl] = useState<number | null>(
    null,
  );
  const [intradayTotalPnl, setIntradayTotalPnl] = useState<number | null>(null);
  const [byAccount, setByAccount] = useState<GroupAccountPnl[]>([]);
  // Account filter for the Open Positions / Trades tables (null = all accounts).
  const [accountFilter, setAccountFilter] = useState<number | null>(null);
  const [marksAsOf, setMarksAsOf] = useState<string | null>(null);
  const [liveSyncing, setLiveSyncing] = useState(false);
  const [liveSyncMessage, setLiveSyncMessage] = useState<string | null>(null);

  const [showNewStrategy, setShowNewStrategy] = useState(false);
  const [newStrategyValue, setNewStrategyValue] = useState("");
  const [showArchivedStrategies, setShowArchivedStrategies] = useState(false);
  const [showNewGroup, setShowNewGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupNotes, setNewGroupNotes] = useState("");
  const [groupFilter, setGroupFilter] = useState<GroupFilter>("active");
  const [groupSort, setGroupSort] = useState<GroupSort>("name");

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

  const visibleGroups = useMemo(() => {
    const filtered =
      groupFilter === "all"
        ? groups
        : groups.filter((group) => {
            const status: TradeGroup["status"] =
              groupFilter === "active" ? "open" : groupFilter;
            return group.status === status;
          });
    return [...filtered].sort((a, b) => {
      if (groupSort === "opened_at") {
        // Most recently opened first; fall back to name for equal timestamps.
        const diff = Date.parse(b.opened_at) - Date.parse(a.opened_at);
        if (diff !== 0) return diff;
      }
      return a.name.localeCompare(b.name, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });
  }, [groups, groupFilter, groupSort]);

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
    return data;
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
    setIntradayUnrealizedPnl(data.intraday_unrealized_pnl);
    setIntradayRealizedPnl(data.intraday_realized_pnl);
    setIntradayTotalPnl(data.intraday_total_pnl);
    setByAccount(data.by_account ?? []);
    setAccountFilter(null);
    setMarksAsOf(data.marks_as_of);
  }, []);

  useEffect(() => {
    let active = true;

    void (async () => {
      try {
        const data = await loadStrategies();
        if (!active) return;

        // A trade group is nested under a strategy. When the page is opened
        // with only a trade_group_id (e.g. a Trade Group link from the
        // Positions page), look up that group's parent strategy and select it
        // so the page lands on the group instead of falling back to the first
        // strategy's first group. Runs once.
        if (!deepLinkResolvedRef.current) {
          deepLinkResolvedRef.current = true;
          const groupId = initialGroupIdRef.current;
          const strategyId = initialStrategyIdRef.current;
          const strategyParamValid =
            strategyId != null &&
            data.some((strategy) => strategy.id === strategyId);
          if (groupId != null && !strategyParamValid) {
            const ownerValue = await fetchGroupStrategyValue(groupId);
            if (!active) return;
            const owner = ownerValue
              ? data.find((strategy) => strategy.value === ownerValue)
              : undefined;
            if (owner) {
              setSelectedStrategyId(owner.id);
              setSelectedGroupId(groupId);
            }
          }
        }
      } catch (loadError: unknown) {
        if (!active) return;
        const nextMessage =
          loadError instanceof Error
            ? loadError.message
            : "Failed to load trade tagging workspace.";
        setError(nextMessage);
      } finally {
        if (active) setLoading(false);
      }
    })();

    return () => {
      active = false;
    };
  }, [loadStrategies]);

  // Keep the URL query params in sync with the current selection so the page
  // is shareable/bookmarkable. Use replace so clicking around doesn't pile up
  // browser history entries.
  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (selectedStrategyId != null) {
          next.set("strategy_id", String(selectedStrategyId));
        } else {
          next.delete("strategy_id");
        }
        if (selectedGroupId != null) {
          next.set("trade_group_id", String(selectedGroupId));
        } else {
          next.delete("trade_group_id");
        }
        return next;
      },
      { replace: true },
    );
  }, [selectedStrategyId, selectedGroupId, setSearchParams]);

  useEffect(() => {
    let active = true;

    // Wait for the initial strategy resolution to finish before loading groups,
    // so a deep-linked trade group isn't cleared while strategies are still
    // loading (selectedStrategy is briefly null on first mount).
    if (loading) return;

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
  }, [loadGroups, selectedStrategy, loading]);

  useEffect(() => {
    if (selectedGroupId == null) {
      setGroupDetail(null);
      setExecutions([]);
      setTotalRealizedPnl(null);
      setOpenPositions([]);
      setTotalUnrealizedPnl(null);
      setIntradayUnrealizedPnl(null);
      setIntradayRealizedPnl(null);
      setIntradayTotalPnl(null);
      setByAccount([]);
      setAccountFilter(null);
      setMarksAsOf(null);
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

  const kickOffIntradaySync = async () => {
    setLiveSyncing(true);
    setLiveSyncMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/positions/sync/intraday-tws`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Refresh live intraday overlay from trade group view.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data: { job_id: number; status: string } = await res.json();
      setLiveSyncMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      // TWS session + reqTickers take longer than a flex enqueue; poll a couple times.
      const refresh = () => {
        if (selectedGroupId != null) void loadExecutions(selectedGroupId);
      };
      window.setTimeout(refresh, 3000);
      window.setTimeout(refresh, 8000);
    } catch (err) {
      setLiveSyncMessage(
        err instanceof Error ? err.message : "Unknown sync error",
      );
    } finally {
      setLiveSyncing(false);
    }
  };

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

  // Account-filtered views of the linked positions/trades (null = all accounts).
  const positionAccountLabel = (p: GroupOpenPosition) =>
    p.account_alias ?? `Account ${p.account_id}`;
  const positionContractLabel = (p: GroupOpenPosition) =>
    p.contract_display ?? p.local_symbol ?? p.symbol ?? `#${p.con_id}`;
  // Option strike parsed from the display (e.g. "CL 70.5 CALL" -> 70.5), used to
  // order strikes numerically instead of lexically. Null for non-options.
  const positionStrike = (p: GroupOpenPosition): number | null => {
    const m = /(-?\d+(?:\.\d+)?)\s+(?:CALL|PUT)/i.exec(
      p.contract_display ?? "",
    );
    return m ? Number.parseFloat(m[1]) : null;
  };
  const visiblePositions = (
    accountFilter == null
      ? openPositions
      : openPositions.filter((p) => p.account_id === accountFilter)
  )
    .slice()
    .sort((a, b) => {
      // account, then symbol, then strike (high -> low), then natural-numeric
      // fallback on the display for anything without a strike (e.g. futures).
      const acct = positionAccountLabel(a).localeCompare(
        positionAccountLabel(b),
      );
      if (acct !== 0) return acct;
      const sym = (a.symbol ?? "").localeCompare(b.symbol ?? "");
      if (sym !== 0) return sym;
      const sa = positionStrike(a);
      const sb = positionStrike(b);
      if (sa != null && sb != null && sa !== sb) return sb - sa;
      return positionContractLabel(a).localeCompare(
        positionContractLabel(b),
        undefined,
        { numeric: true },
      );
    });
  // Google-Sheets-style banding: each account group gets a subtle alternating
  // background so rows read as grouped by account.
  const positionAccountBand = new Map<number, number>();
  for (const p of visiblePositions) {
    if (!positionAccountBand.has(p.account_id)) {
      positionAccountBand.set(p.account_id, positionAccountBand.size % 2);
    }
  }
  const visibleExecutions =
    accountFilter == null
      ? executions
      : executions.filter((e) => e.account_id === accountFilter);

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
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(280px,35%)_1fr]">
            {/* Group list */}
            <div className="flex min-h-0 flex-col">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h3 className="text-sm font-semibold">
                  Trade Groups
                  {selectedStrategy && (
                    <span className="ml-1 font-normal text-gray-500">
                      ({selectedStrategy.value})
                    </span>
                  )}
                </h3>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setShowNewGroup(!showNewGroup)}
                    disabled={!selectedStrategy}
                    className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {showNewGroup ? "Cancel" : "+ New"}
                  </button>
                  <select
                    value={groupSort}
                    onChange={(event) =>
                      setGroupSort(event.target.value as GroupSort)
                    }
                    aria-label="Sort trade groups"
                    title="Sort trade groups"
                    className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
                  >
                    {GROUP_SORTS.map((sort) => (
                      <option key={sort.value} value={sort.value}>
                        {sort.label}
                      </option>
                    ))}
                  </select>
                  <select
                    value={groupFilter}
                    onChange={(event) =>
                      setGroupFilter(event.target.value as GroupFilter)
                    }
                    aria-label="Filter trade groups by status"
                    title="Filter trade groups by status"
                    className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
                  >
                    {GROUP_FILTERS.map((filter) => (
                      <option key={filter.value} value={filter.value}>
                        {filter.label}
                      </option>
                    ))}
                  </select>
                </div>
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

              <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
                {loadingGroups && (
                  <li className="text-xs text-gray-500">
                    Loading trade groups...
                  </li>
                )}
                {!loadingGroups &&
                  visibleGroups.map((group) => (
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
                {!loadingGroups && visibleGroups.length === 0 && (
                  <li className="rounded border border-dashed border-gray-300 px-2 py-3 text-xs text-gray-500">
                    {!selectedStrategy
                      ? "Select a strategy to view trade groups."
                      : groups.length === 0
                        ? "No trade groups for this strategy yet."
                        : `No ${groupFilter === "all" ? "" : groupFilter + " "}trade groups for this strategy.`}
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
                    <button
                      onClick={() => {
                        void kickOffIntradaySync();
                      }}
                      disabled={liveSyncing}
                      className="rounded border border-emerald-300 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
                    >
                      {liveSyncing ? "Queueing…" : "Refresh Live (TWS)"}
                    </button>
                  </div>
                  {liveSyncMessage && (
                    <p className="text-xs text-emerald-700">
                      {liveSyncMessage}
                    </p>
                  )}

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
                      // IBKR avg_cost is already multiplier-inclusive (per-contract
                      // for options/futures, per-share for stocks), so a leg's cost
                      // basis is avg_cost * position. Accumulate the SIGNED basis so
                      // long and short legs of a spread net out — a calendar/vertical
                      // spread's real capital is the net debit, not the gross notional
                      // of both legs (which over-counts ~2x+ for offsetting legs).
                      let optionsSum = 0;
                      let equitySum = 0;
                      for (const pos of openPositions) {
                        const posBasis = pos.avg_cost * pos.position;
                        if (pos.sec_type === "OPT" || pos.sec_type === "FOP") {
                          optionsSum += posBasis;
                        } else {
                          equitySum += posBasis;
                        }
                      }
                      // Magnitude of each bucket's net basis: a net debit (capital
                      // outlaid) and a net credit (premium received) both represent
                      // capital committed, so report the absolute value per bucket.
                      const optionsAbs = Math.abs(optionsSum);
                      const equityAbs = Math.abs(equitySum);
                      if (optionsAbs + equityAbs > 0) {
                        optionsCapital = optionsAbs;
                        equityCapital = equityAbs;
                        capital = optionsAbs + equityAbs;
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
                        <div className="my-1 border-t border-gray-200" />
                        <div className="flex items-baseline justify-between">
                          <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                            Intraday (live)
                          </span>
                          <span className="text-[11px] text-gray-400">
                            {marksAsOf
                              ? `live as of ${formatMarkTime(marksAsOf)}`
                              : "settled — no live data"}
                          </span>
                        </div>
                        {row("Total PnL", intradayTotalPnl, true, true)}
                        {row(
                          "Unrealized PnL",
                          intradayUnrealizedPnl,
                          true,
                          true,
                        )}
                        {row("Realized PnL", intradayRealizedPnl, true, true)}
                      </div>
                    );
                  })()}

                  {/* Per-account breakdown (only meaningful with >1 account) */}
                  {byAccount.length > 1 &&
                    (() => {
                      const money = (v: number | null) =>
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
                      // Per-account capital: net signed cost basis per bucket, then
                      // magnitude — same convention as the group capital above so
                      // spread legs net out rather than double-counting.
                      const capitalFor = (accountId: number) => {
                        let optionsSum = 0;
                        let equitySum = 0;
                        let any = false;
                        for (const pos of openPositions) {
                          if (pos.account_id !== accountId) continue;
                          any = true;
                          const basis = pos.avg_cost * pos.position;
                          if (pos.sec_type === "OPT" || pos.sec_type === "FOP")
                            optionsSum += basis;
                          else equitySum += basis;
                        }
                        if (!any) return null;
                        return Math.abs(optionsSum) + Math.abs(equitySum);
                      };
                      const gridCols =
                        "grid grid-cols-[6rem_1fr_1fr_1fr_1fr] items-baseline gap-x-2";
                      return (
                        <div className="flex flex-col gap-1 rounded border border-gray-200 bg-white px-3 py-2 text-xs">
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
                            By account
                          </div>
                          <div
                            className={`${gridCols} border-b border-gray-100 pb-1 text-[11px] font-medium uppercase tracking-wide text-gray-400`}
                          >
                            <span>Account</span>
                            <span className="text-right">Capital</span>
                            <span className="text-right">Total</span>
                            <span className="text-right">Realized</span>
                            <span className="text-right">Unrealized</span>
                          </div>
                          {byAccount.map((acct) => {
                            const total =
                              acct.unrealized_pnl == null &&
                              acct.realized_pnl == null
                                ? null
                                : (acct.unrealized_pnl ?? 0) +
                                  (acct.realized_pnl ?? 0);
                            const capital = capitalFor(acct.account_id);
                            return (
                              <div key={acct.account_id} className={gridCols}>
                                <span className="font-medium text-gray-700">
                                  {acct.account_alias ?? acct.account_id}
                                </span>
                                <span className="text-right text-gray-500">
                                  {money(capital)}
                                </span>
                                <span className={`text-right ${cls(total)}`}>
                                  {money(total)}
                                </span>
                                <span
                                  className={`text-right ${cls(acct.realized_pnl)}`}
                                >
                                  {money(acct.realized_pnl)}
                                </span>
                                <span
                                  className={`text-right ${cls(acct.unrealized_pnl)}`}
                                >
                                  {money(acct.unrealized_pnl)}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}

                  {/* Account filter — splits the tables below by account */}
                  {(() => {
                    const accounts = byAccount.length
                      ? byAccount.map((a) => ({
                          id: a.account_id,
                          label: a.account_alias ?? `Account ${a.account_id}`,
                        }))
                      : [];
                    if (accounts.length <= 1) return null;
                    const chip = (
                      active: boolean,
                      label: string,
                      onClick: () => void,
                      key: string | number,
                    ) => (
                      <button
                        key={key}
                        type="button"
                        onClick={onClick}
                        className={`rounded-full border px-2.5 py-0.5 text-xs ${
                          active
                            ? "border-gray-800 bg-gray-800 text-white"
                            : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
                        }`}
                      >
                        {label}
                      </button>
                    );
                    return (
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="text-xs text-gray-500">Account:</span>
                        {chip(
                          accountFilter == null,
                          "All",
                          () => setAccountFilter(null),
                          "all",
                        )}
                        {accounts.map((a) =>
                          chip(
                            accountFilter === a.id,
                            a.label,
                            () => setAccountFilter(a.id),
                            a.id,
                          ),
                        )}
                      </div>
                    );
                  })()}

                  {/* Open Positions */}
                  <div>
                    <div className="mb-2 flex items-baseline justify-between">
                      <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
                        Open Positions ({visiblePositions.length}
                        {accountFilter != null
                          ? ` of ${openPositions.length}`
                          : ""}
                        )
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
                    {visiblePositions.length === 0 && (
                      <p className="mb-3 text-xs text-gray-400">
                        No open positions linked to this group.
                      </p>
                    )}
                    {visiblePositions.length > 0 && (
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
                                Live Mark
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Value
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Unrealized
                              </th>
                              <th className="px-2 py-1 text-right font-medium">
                                Live Unrealized
                              </th>
                              <th className="px-2 py-1 font-medium">As of</th>
                              <th className="px-2 py-1 font-medium">Source</th>
                            </tr>
                          </thead>
                          <tbody>
                            {visiblePositions.map((pos) => {
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
                              const livePnlClass =
                                pos.live_unrealized == null
                                  ? "text-gray-400"
                                  : pos.live_unrealized >= 0
                                    ? "text-emerald-700"
                                    : "text-red-700";
                              return (
                                <tr
                                  key={`${pos.account_id}-${pos.con_id}`}
                                  className={`border-t border-gray-100 ${
                                    positionAccountBand.get(pos.account_id) ===
                                    1
                                      ? "bg-gray-50"
                                      : "bg-white"
                                  }`}
                                >
                                  <td className="px-2 py-1 text-gray-700">
                                    {positionAccountLabel(pos)}
                                  </td>
                                  <td className="px-2 py-1 text-gray-800">
                                    {positionContractLabel(pos)}
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
                                    {pos.mark == null
                                      ? "—"
                                      : pos.mark.toFixed(2)}
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
                                  <td
                                    className={`px-2 py-1 text-right font-mono ${livePnlClass}`}
                                  >
                                    {pos.live_unrealized == null
                                      ? "—"
                                      : pos.live_unrealized.toFixed(2)}
                                  </td>
                                  <td className="px-2 py-1 text-gray-500">
                                    {pos.as_of_date ?? "—"}
                                  </td>
                                  <td className="px-2 py-1">
                                    {pos.source === "live" ? (
                                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800">
                                        live
                                        {pos.mark_ts
                                          ? ` ${formatMarkTime(pos.mark_ts)}`
                                          : ""}
                                      </span>
                                    ) : (
                                      <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600">
                                        settled
                                      </span>
                                    )}
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
                        Trades ({visibleExecutions.length}
                        {accountFilter != null
                          ? ` of ${executions.length}`
                          : ""}
                        )
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
                    {visibleExecutions.length === 0 && (
                      <p className="mb-3 text-xs text-gray-400">
                        No trades assigned to this group yet.
                      </p>
                    )}
                    {visibleExecutions.length > 0 && (
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
                              const withRunning = visibleExecutions.map(
                                (ex) => {
                                  const counted =
                                    ex.realized_pnl != null &&
                                    ex.exec_role !== "combo_summary";
                                  if (counted)
                                    running += ex.realized_pnl as number;
                                  return { ex, counted, running };
                                },
                              );
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
                                          (ex.trade_id != null
                                            ? `#${ex.trade_id}`
                                            : "—")}
                                        {ex.exec_role !== "standalone" && (
                                          <span className="ml-1 rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase text-gray-500">
                                            {ex.exec_role}
                                          </span>
                                        )}
                                        {ex.settled === false && (
                                          <span className="ml-1 rounded bg-amber-100 px-1 py-0.5 text-[10px] uppercase text-amber-800">
                                            unsettled
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
