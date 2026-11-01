// The Trade Group cell of an execution row: the assigned group as a link
// with a swap affordance, or an assign button, backed by the trade-group
// search picker. Applies the choice optimistically and reverts on failure.

import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { tradeGroupLabel } from "../../lib/tradeGroups";
import type { TradeGroupResult } from "../../types/tradeGroups";
import TradeGroupSearchSelect from "../TradeGroupSearchSelect";

export default function TradeGroupCell({
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
  // Unsettled live fills are grouped per-fill by ib_exec_id, not via the trade fan-out.
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

  // An override stops being pending as soon as the backend-confirmed prop
  // catches up to it; from then on the authoritative server values win. Derived
  // during render rather than cleared in an effect, so there is no intermediate
  // pass where the settled override is still on screen.
  const pendingOverride =
    optimisticOverride && optimisticOverride.id !== assignedTradeGroupId
      ? optimisticOverride
      : null;

  // The group currently shown to the user: the optimistic value when one is
  // pending, otherwise the backend-confirmed prop.
  const effectiveGroupId = pendingOverride
    ? pendingOverride.id
    : assignedTradeGroupId;
  const effectiveLabel = pendingOverride ? pendingOverride.label : groupLabel;

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
        await api.post(
          `/trade-groups/${group.id}/live-executions:assign`,
          {
            ib_exec_ids: [ibExecId],
            source: "manual",
            created_by: "ui-trader",
            reason: `live fill ${ibExecId} assigned from trades page`,
          },
          { fallback: "Unable to assign fill" },
        );
        onAssigned();
        return;
      }

      const tradeExecutions = await api.get<{ id: number }[]>(
        `/trades/${tradeId}/executions`,
        { fallback: "Unable to load executions" },
      );
      const executionIds = tradeExecutions.map((ex) => ex.id);
      if (executionIds.length === 0) {
        throw new Error("Trade has no executions to assign.");
      }

      await api.post(
        `/trade-groups/${group.id}/executions:assign`,
        {
          execution_ids: executionIds,
          source: "manual",
          created_by: "ui-trader",
          reason: `trade ${tradeId} assigned from trades page`,
          force_reassign: true,
        },
        { fallback: "Unable to assign trade" },
      );

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
        await api.post(
          `/trade-groups/${groupId}/live-executions:unassign`,
          {
            ib_exec_ids: [ibExecId],
            source: "manual",
            created_by: "ui-trader",
            reason: `live fill ${ibExecId} unassigned from trades page`,
          },
          { fallback: "Unable to unassign fill" },
        );
        onAssigned();
        return;
      }

      const tradeExecutions = await api.get<{ id: number }[]>(
        `/trades/${tradeId}/executions`,
        { fallback: "Unable to load executions" },
      );
      const executionIds = tradeExecutions.map((ex) => ex.id);

      await api.post(
        `/trade-groups/${groupId}/executions:unassign`,
        {
          execution_ids: executionIds,
          source: "manual",
          created_by: "ui-trader",
          reason: `trade ${tradeId} unassigned from trades page`,
        },
        { fallback: "Unable to unassign trade" },
      );

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
            // Two affordances in one badge: the name links to the trade group
            // detail view, the swap icon opens the reassign finder.
            <span
              className={`inline-flex items-center whitespace-nowrap rounded bg-blue-100 text-xs font-medium text-blue-800 ${
                assigning ? "opacity-60" : ""
              }`}
            >
              <Link
                to={`/strategies?trade_group_id=${effectiveGroupId}`}
                onClick={(e) => e.stopPropagation()}
                className="rounded-l px-1.5 py-0.5 hover:bg-blue-200 hover:underline"
                title="Open trade group detail"
              >
                {effectiveLabel ?? `Group #${effectiveGroupId}`}
              </Link>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  open();
                }}
                disabled={assigning}
                className="rounded-r px-1 py-0.5 hover:bg-blue-200 disabled:opacity-50"
                title={assigning ? "Saving…" : "Change trade group"}
                aria-label={`Change trade group (currently ${
                  effectiveLabel ?? `#${effectiveGroupId}`
                })`}
              >
                &#8646;
              </button>
            </span>
          ) : (
            <button
              type="button"
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
          type="button"
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
