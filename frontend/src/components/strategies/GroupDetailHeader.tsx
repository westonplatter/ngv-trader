// Top of a group's detail: name and status, the focus toggle, the opened /
// closed / executions / strategy grid, tags, tasks, notes, meta YAML, and the
// Edit / Delete / Refresh Live actions.

import type { TradeGroupDetail } from "../../types/tradeGroups";
import { formatDateTime } from "../../utils/date";
import { linkify } from "../../utils/linkify";
import GroupTasks from "../GroupTasks";
import TagChips from "../TagChips";
import { statusClassName } from "./statusStyles";
import type { GroupLiveSync } from "./useGroupLiveSync";

export default function GroupDetailHeader({
  detail,
  strategyName,
  focusActive,
  onToggleFocus,
  onTagsChanged,
  onTasksChanged,
  onEdit,
  onDelete,
  liveSync,
}: {
  detail: TradeGroupDetail;
  strategyName: string | null;
  focusActive: boolean;
  onToggleFocus: () => void;
  onTagsChanged: () => void;
  onTasksChanged: () => void;
  onEdit: () => void;
  onDelete: () => void;
  liveSync: GroupLiveSync;
}) {
  return (
    <>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {/* Breadcrumb keeps the hidden lists' context in view while
              focused (the strategy/group panes are collapsed). */}
          {focusActive && (
            <p className="mb-0.5 truncate text-xs text-gray-400">
              {strategyName && <span>{strategyName} › </span>}
              <span className="text-gray-500">{detail.name}</span>
            </p>
          )}
          <h4 className="truncate text-base font-semibold text-gray-900">
            {detail.name}
          </h4>
          <p className="text-xs text-gray-500">#{detail.id}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <span
            className={`rounded px-2 py-0.5 text-xs font-semibold uppercase ${statusClassName(detail.status)}`}
          >
            {detail.status}
          </span>
          <button
            type="button"
            onClick={onToggleFocus}
            aria-pressed={focusActive}
            title={
              focusActive
                ? "Exit focus mode (F or Esc)"
                : "Focus mode — hide lists, full-width detail (F)"
            }
            className={`rounded border px-1.5 py-0.5 text-xs ${
              focusActive
                ? "border-blue-300 bg-blue-50 text-blue-700"
                : "border-gray-300 text-gray-500 hover:bg-gray-50"
            }`}
          >
            {focusActive ? "⤡" : "⤢"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
        <div>
          <span className="text-xs text-gray-500">Opened</span>
          <p className="text-gray-800">{formatDateTime(detail.opened_at)}</p>
        </div>
        <div>
          <span className="text-xs text-gray-500">Closed</span>
          <p className="text-gray-800">{formatDateTime(detail.closed_at)}</p>
        </div>
        <div>
          <span className="text-xs text-gray-500">Executions</span>
          <p className="text-gray-800">{detail.execution_count}</p>
        </div>
        <div>
          <span className="text-xs text-gray-500">Strategy</span>
          <p className="text-gray-800">
            {detail.primary_strategy_value ?? "None"}
          </p>
        </div>
      </div>

      <div>
        <span className="text-xs text-gray-500">Tags</span>
        <div className="mt-0.5">
          <TagChips
            item={{ entity_type: "trade_group", id: detail.id }}
            tags={detail.tags ?? []}
            onChanged={onTagsChanged}
          />
        </div>
      </div>

      <GroupTasks
        // Remount per group so an in-flight load or a half-typed task never
        // lands on the next group selected.
        key={detail.id}
        tradeGroupId={detail.id}
        onChanged={onTasksChanged}
      />

      {detail.notes && (
        <div>
          <span className="text-xs text-gray-500">Notes</span>
          <p className="mt-0.5 whitespace-pre-wrap text-sm text-gray-700">
            {linkify(detail.notes)}
          </p>
        </div>
      )}

      {detail.meta_yaml && (
        <details className="group">
          <summary className="cursor-pointer list-none text-xs text-gray-500 hover:text-gray-700">
            <span className="mr-1 inline-block transition-transform group-open:rotate-90">
              ▶
            </span>
            Meta (YAML)
          </summary>
          <pre className="mt-0.5 overflow-x-auto rounded border border-gray-200 bg-gray-50 p-2 font-mono text-xs leading-relaxed text-gray-700">
            {detail.meta_yaml}
          </pre>
        </details>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onEdit}
          className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-700 hover:bg-gray-50"
        >
          Edit
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="rounded border border-red-200 px-3 py-1 text-xs text-red-600 hover:bg-red-50"
        >
          Delete
        </button>
        <button
          type="button"
          onClick={() => {
            void liveSync.kickOff();
          }}
          disabled={liveSync.syncing}
          className="rounded border border-emerald-300 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          {liveSync.syncing ? "Queueing…" : "Refresh Live (TWS)"}
        </button>
      </div>
      {liveSync.message && (
        <p className="text-xs text-emerald-700">{liveSync.message}</p>
      )}
    </>
  );
}
