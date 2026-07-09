import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";
import { API_BASE_URL } from "../config";
import { useSSE } from "../lib/events";
import { formatMoney } from "../utils/number";
import TradeGroupSearchSelect from "./TradeGroupSearchSelect";
import { type TradeGroupResult, tradeGroupLabel } from "../lib/tradeGroups";

interface TradeExecutionRow {
  id: number;
  trade_id: number | null;
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
  con_id: number | null;
  contract_display: string | null;
  parent_ib_exec_id: string | null;
  data_source?: string;
  trade_ib_perm_id: number | null;
  trade_order_ref: string | null;
  trade_status: string;
  trade_lifecycle: string | null;
  trade_contract_display_name: string | null;
  trade_realized_pnl: number | null;
  trade_assigned_trade_group_id: number | null;
  trade_first_executed_at: string | null;
  trade_last_executed_at: string | null;
  // Unsettled TWS overlay: false for live fills not yet settled.
  settled?: boolean;
  live_trade_group_id?: number | null;
}

const STATUS_CLASS: Record<string, string> = {
  filled: "bg-emerald-100 text-emerald-800",
  partial: "bg-blue-100 text-blue-800",
  cancelled: "bg-zinc-200 text-zinc-800",
  expired: "bg-purple-100 text-purple-800",
  assigned: "bg-orange-100 text-orange-800",
  exercised: "bg-teal-100 text-teal-800",
  unknown: "bg-gray-100 text-gray-800",
  unsettled: "bg-amber-100 text-amber-800",
};

// Effective trade-group membership for a row. Settled rows carry trade-level
// membership; unsettled live fills carry their own per-fill membership.
function rowGroupId(row: TradeExecutionRow): number | null {
  return row.settled === false
    ? (row.live_trade_group_id ?? null)
    : row.trade_assigned_trade_group_id;
}

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
  unsettled = false,
  ibExecId = null,
}: {
  tradeId: number | null;
  accountId: number;
  contractDisplayName: string | null;
  assignedTradeGroupId: number | null;
  groupLabel: string | null;
  onAssigned: () => void;
  // Unsettled live fills tag per-fill by ib_exec_id, not via the trade fan-out.
  unsettled?: boolean;
  ibExecId?: string | null;
}) {
  const [assigning, setAssigning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Optimistic override applied as soon as the user picks/clears a group, before
  // the backend confirms. `id === null` represents an optimistic unassign.
  const [optimisticOverride, setOptimisticOverride] = useState<{
    id: number | null;
    label: string | null;
  } | null>(null);

  // Once the backend-confirmed prop catches up to (or matches) the optimistic
  // target, drop the override so we render the authoritative server state.
  useEffect(() => {
    if (optimisticOverride && assignedTradeGroupId === optimisticOverride.id) {
      setOptimisticOverride(null);
    }
  }, [assignedTradeGroupId, optimisticOverride]);

  // The group currently shown to the user: the optimistic value when one is
  // pending, otherwise the backend-confirmed prop.
  const effectiveGroupId = optimisticOverride
    ? optimisticOverride.id
    : assignedTradeGroupId;
  const effectiveLabel = optimisticOverride
    ? optimisticOverride.label
    : groupLabel;

  const assignToGroup = async (group: TradeGroupResult) => {
    const previousOverride = optimisticOverride;
    // Apply the label immediately so the UI feels instant. The search popover
    // closes itself before invoking this handler.
    setOptimisticOverride({ id: group.id, label: tradeGroupLabel(group) });
    setError(null);
    setAssigning(true);
    try {
      if (unsettled) {
        if (!ibExecId) throw new Error("Missing live execution id.");
        const assignResponse = await fetch(
          `${API_BASE_URL}/trade-groups/${group.id}/live-executions:assign`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ib_exec_ids: [ibExecId],
              source: "manual",
              created_by: "ui-trader",
              reason: `live fill ${ibExecId} assigned from trades page`,
            }),
          },
        );
        if (!assignResponse.ok) {
          throw new Error(
            await readErrorMessage(assignResponse, "Unable to assign fill"),
          );
        }
        onAssigned();
        return;
      }

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
        `${API_BASE_URL}/trade-groups/${group.id}/executions:assign`,
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

      // Confirmed — refresh parent data. The clear-override effect drops the
      // optimistic value once the prop reflects the assignment.
      onAssigned();
    } catch (err) {
      // Revert to whatever was shown before this attempt and surface the error.
      setOptimisticOverride(previousOverride);
      setError(err instanceof Error ? err.message : "Assignment failed");
    } finally {
      setAssigning(false);
    }
  };

  const unassignFromGroup = async () => {
    if (!effectiveGroupId) return;
    const groupId = effectiveGroupId;
    const previousOverride = optimisticOverride;
    // Optimistically clear the label, reverting if the request fails.
    setOptimisticOverride({ id: null, label: null });
    setError(null);
    setAssigning(true);
    try {
      if (unsettled) {
        if (!ibExecId) throw new Error("Missing live execution id.");
        const unassignResponse = await fetch(
          `${API_BASE_URL}/trade-groups/${groupId}/live-executions:unassign`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ib_exec_ids: [ibExecId],
              source: "manual",
              created_by: "ui-trader",
              reason: `live fill ${ibExecId} unassigned from trades page`,
            }),
          },
        );
        if (!unassignResponse.ok) {
          throw new Error(
            await readErrorMessage(unassignResponse, "Unable to unassign fill"),
          );
        }
        onAssigned();
        return;
      }

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
        `${API_BASE_URL}/trade-groups/${groupId}/executions:unassign`,
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
      setOptimisticOverride(previousOverride);
      setError(err instanceof Error ? err.message : "Unassign failed");
    } finally {
      setAssigning(false);
    }
  };

  return (
    <div className="flex items-center gap-1">
      <TradeGroupSearchSelect
        accountId={accountId}
        contractDisplayName={contractDisplayName}
        onSelect={assignToGroup}
        disabled={assigning}
        renderTrigger={(open) =>
          effectiveGroupId ? (
            <span
              className={`whitespace-nowrap rounded bg-blue-100 px-2 py-0.5 text-xs font-medium text-blue-800 cursor-pointer hover:bg-blue-200 ${
                assigning ? "opacity-60" : ""
              }`}
              onClick={(e) => {
                e.stopPropagation();
                open();
              }}
              title={assigning ? "Saving…" : "Click to reassign"}
            >
              {effectiveLabel ?? `Group #${effectiveGroupId}`}
            </span>
          ) : (
            <button
              onClick={(e) => {
                e.stopPropagation();
                open();
              }}
              className="rounded border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-400 hover:border-blue-300 hover:text-blue-600"
            >
              + Assign
            </button>
          )
        }
      />
      {effectiveGroupId && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (window.confirm(`Unassign from group #${effectiveGroupId}?`)) {
              void unassignFromGroup();
            }
          }}
          disabled={assigning}
          className="flex h-5 w-5 items-center justify-center rounded text-sm font-bold text-gray-400 hover:bg-red-100 hover:text-red-600 disabled:opacity-50"
          title="Unassign from group"
        >
          ×
        </button>
      )}
      {error && (
        <span className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600">
          {error}
        </span>
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
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  const [searchParams] = useSearchParams();
  const [symbolFilter, setSymbolFilter] = useState(
    () => searchParams.get("symbol") ?? "",
  );
  const [accountFilter, setAccountFilter] = useState<string>("all");
  // Default to the last 30 days for performance (fewer rows rendered). The
  // con_id deep-link case wants every execution for a contract, so it opts out.
  const [timeRange, setTimeRange] = useState<string>(() =>
    searchParams.get("con_id") ? "all" : "30d",
  );
  const [tagStatus, setTagStatus] = useState<"all" | "tagged" | "untagged">(
    "all",
  );
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

  // When the page is opened via a Positions "Con ID" link (/trades?con_id=123),
  // fetch every execution for that contract across all time and all accounts.
  const conIdFilter = useMemo(() => {
    const raw = searchParams.get("con_id");
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isInteger(parsed) ? parsed : null;
  }, [searchParams]);

  const loadExecutions = useCallback(async () => {
    const params = new URLSearchParams({ limit: "5000" });
    if (conIdFilter !== null) params.set("con_id", String(conIdFilter));
    else if (serverSymbol) params.set("symbol", serverSymbol);
    const res = await fetch(
      `${API_BASE_URL}/trade-executions?${params.toString()}`,
    );
    if (!res.ok) {
      throw new Error(await readErrorMessage(res, "Unable to load executions"));
    }
    const data: TradeExecutionRow[] = await res.json();
    setExecutions(data);
    setError(null);
  }, [serverSymbol, conIdFilter]);

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
    if (tagStatus !== "all") {
      next = next.filter((row) =>
        tagStatus === "tagged"
          ? rowGroupId(row) !== null
          : rowGroupId(row) === null,
      );
    }
    // Newest first by execution time, regardless of settled/unsettled — so the
    // most recent fills (including today's unsettled TWS fills) sit at the top.
    // Stable sort keeps same-timestamp combo/leg rows in their existing order.
    const execMs = (row: TradeExecutionRow) => {
      const t = Date.parse(row.executed_at);
      return Number.isNaN(t) ? Number.NEGATIVE_INFINITY : t;
    };
    return [...next].sort((a, b) => execMs(b) - execMs(a));
  }, [executions, accountFilter, symbolRegex, timeRange, tagStatus]);

  // For each trade_id, the row that owns the Tag Group cell.
  // Prefer combo_summary; otherwise the earliest row in the filtered view.
  const tagGroupRowIdByTradeId = useMemo(() => {
    const map = new Map<number, number>();
    for (const row of filteredRows) {
      // Live fills have no parent trade; each owns its own tag cell (below).
      if (row.trade_id === null) continue;
      if (row.exec_role === "combo_summary") {
        map.set(row.trade_id, row.id);
      }
    }
    for (const row of filteredRows) {
      if (row.trade_id === null) continue;
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
    options: {
      days?: number;
      sinceLastTrade?: boolean;
      startDate?: string;
      endDate?: string;
    },
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
          ...(options.startDate && options.endDate
            ? { start_date: options.startDate, end_date: options.endDate }
            : {}),
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
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Trades</h2>
          <p className="text-xs text-gray-500">
            {filteredRows.length} execution(s)
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
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
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-gray-500">
              Sync range:
            </span>
            <input
              type="date"
              value={rangeStart}
              onChange={(event) => setRangeStart(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-700"
              aria-label="Sync start date"
            />
            <span className="text-xs text-gray-400">→</span>
            <input
              type="date"
              value={rangeEnd}
              onChange={(event) => setRangeEnd(event.target.value)}
              className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-700"
              aria-label="Sync end date"
            />
            <button
              onClick={() => {
                void kickOffTradesSync("Range sync", {
                  startDate: rangeStart,
                  endDate: rangeEnd,
                });
              }}
              disabled={
                syncing || !rangeStart || !rangeEnd || rangeStart > rangeEnd
              }
              title="Sync trades for an explicit date range (FlexQuery is T-1, so the end date must be the previous business day or earlier)"
              className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
            >
              {syncing ? "Queueing..." : "Sync Range"}
            </button>
          </div>
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

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Range
          </span>
          <div className="inline-flex items-center gap-0.5 rounded-md bg-gray-100 p-0.5">
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
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
            Tags
          </span>
          <div className="inline-flex items-center gap-0.5 rounded-md bg-gray-100 p-0.5">
            {[
              { id: "all", label: "All" },
              { id: "tagged", label: "Tagged" },
              { id: "untagged", label: "Untagged" },
            ].map((opt) => (
              <button
                key={opt.id}
                onClick={() =>
                  setTagStatus(opt.id as "all" | "tagged" | "untagged")
                }
                className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
                  tagStatus === opt.id
                    ? "bg-white text-gray-900 shadow-sm"
                    : "text-gray-600 hover:text-gray-900"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {conIdFilter !== null && (
        <p className="text-sm text-gray-600">
          Showing all executions for Contract ID{" "}
          <span className="font-mono font-medium">{conIdFilter}</span> across
          all time and accounts.{" "}
          <Link to="/trades" className="text-blue-600 hover:underline">
            Clear
          </Link>
        </p>
      )}
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
              <th className="w-8 whitespace-nowrap px-1 py-2 font-semibold text-gray-700">
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
              <th className="w-48 min-w-[12rem] whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Tag Group
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Parent Exec ID
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Order Ref
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Exec ID
              </th>
              <th className="whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
                Con ID
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
                row.settled === false ||
                (row.trade_id !== null &&
                  tagGroupRowIdByTradeId.get(row.trade_id) === row.id);
              const isHighlighted =
                row.trade_id !== null && highlightedTradeId === row.trade_id;
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
                  <td className="whitespace-nowrap px-1 py-2 text-xs text-gray-700">
                    {row.sec_type ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {row.side ?? "-"}
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
                    {privacyMode ? PRIVACY_MASK : row.quantity}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {privacyMode ? PRIVACY_MASK : formatMoney(row.price, "-")}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-gray-700">
                    {privacyMode
                      ? PRIVACY_MASK
                      : formatMoney(row.realized_pnl, "-")}
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
                        assignedTradeGroupId={rowGroupId(row)}
                        groupLabel={
                          rowGroupId(row) !== null
                            ? (groupLabelById.get(rowGroupId(row)!) ?? null)
                            : null
                        }
                        onAssigned={handleTradeAssigned}
                        unsettled={row.settled === false}
                        ibExecId={row.ib_exec_id}
                      />
                    ) : null}
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
                          onClick={() =>
                            row.trade_id !== null &&
                            toggleHighlight(row.trade_id)
                          }
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
                  <td className="max-w-[200px] truncate whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-600">
                    {privacyMode ? PRIVACY_MASK : row.ib_exec_id}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-600">
                    {row.con_id ?? "-"}
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
