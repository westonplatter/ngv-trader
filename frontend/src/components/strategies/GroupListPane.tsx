// The trade-group list for the selected strategy: sort and status filter,
// the inline "+ New" form, the sectioned list, and the column drag handle.

import { useState } from "react";
import type { ResizableColumn } from "../../hooks/useResizableColumn";
import { errorMessage } from "../../lib/api";
import {
  GROUP_FILTERS,
  GROUP_SORTS,
  STATUS_LABELS,
  type GroupFilter,
  type GroupSection,
  type GroupSort,
} from "../../lib/strategies/groups";
import type { Strategy } from "../../types/strategies";
import type { TradeGroup } from "../../types/tradeGroups";
import { formatDateTime } from "../../utils/date";
import { makeFormatters } from "../../utils/maskedFormatters";
import { TagChipView } from "../TagChips";
import { statusClassName, statusHeaderClassName } from "./statusStyles";

export default function GroupListPane({
  strategy,
  groups,
  sections,
  loading,
  selectedId,
  onSelect,
  filter,
  onFilter,
  sort,
  onSort,
  onCreate,
  column,
  focusActive,
  privacyMode,
  onError,
}: {
  strategy: Strategy | null;
  // All groups of the strategy (for the empty-state copy); null while loading.
  groups: TradeGroup[] | null;
  sections: GroupSection[];
  loading: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
  filter: GroupFilter;
  onFilter: (value: GroupFilter) => void;
  sort: GroupSort;
  onSort: (value: GroupSort) => void;
  onCreate: (name: string, notes: string) => Promise<void>;
  column: ResizableColumn;
  focusActive: boolean;
  privacyMode: boolean;
  onError: (message: string) => void;
}) {
  const fmt = makeFormatters(privacyMode);
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState("");
  const [newNotes, setNewNotes] = useState("");

  const submit = () => {
    onCreate(newName, newNotes)
      .then(() => {
        setNewName("");
        setNewNotes("");
        setShowNew(false);
      })
      .catch((err: unknown) =>
        onError(errorMessage(err, "Failed to create trade group.")),
      );
  };

  return (
    // Collapses to zero width in focus mode. `inert` keeps its hidden controls
    // out of the tab order while collapsed.
    <div
      inert={focusActive}
      className={`relative flex min-h-0 min-w-0 flex-col ${
        focusActive ? "overflow-hidden" : ""
      }`}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold">
          Trade Groups
          {strategy && (
            <span className="ml-1 font-normal text-gray-500">
              ({strategy.name})
            </span>
          )}
        </h3>
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowNew(!showNew)}
            disabled={!strategy}
            className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {showNew ? "Cancel" : "+ New"}
          </button>
          <select
            value={sort}
            onChange={(event) => onSort(event.target.value as GroupSort)}
            aria-label="Sort trade groups"
            title="Sort trade groups"
            className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
          >
            {GROUP_SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <select
            value={filter}
            onChange={(event) => onFilter(event.target.value as GroupFilter)}
            aria-label="Filter trade groups by status"
            title="Filter trade groups by status"
            className="rounded border border-gray-300 bg-white px-1.5 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
          >
            {GROUP_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {showNew && strategy && (
        <div className="mb-3 space-y-2 rounded border border-dashed border-gray-300 p-2">
          <div className="flex items-center gap-2">
            <span className="shrink-0 rounded bg-gray-100 px-2 py-1 text-xs text-gray-600">
              {strategy.name}
            </span>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
              placeholder="Trade group name"
              onKeyDown={(e) => {
                if (e.key === "Enter") submit();
              }}
            />
          </div>
          <textarea
            value={newNotes}
            onChange={(event) => setNewNotes(event.target.value)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
            placeholder="Optional notes"
            rows={1}
          />
          <button
            type="button"
            onClick={submit}
            className="w-full rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50"
          >
            Create Trade Group
          </button>
        </div>
      )}

      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
        {loading && (
          <li className="text-xs text-gray-500">Loading trade groups...</li>
        )}
        {!loading &&
          sections.map((section) => (
            <li key={section.status ?? "flat"}>
              {section.status && (
                <div className="mb-2 mt-5 flex items-center gap-2 border-b border-gray-200 pb-1 first:mt-0">
                  <span
                    className={`text-sm font-bold uppercase tracking-wide ${statusHeaderClassName(section.status)}`}
                  >
                    {STATUS_LABELS[section.status]}
                  </span>
                  <span className="text-xs font-semibold text-gray-400">
                    {section.groups.length}
                  </span>
                </div>
              )}
              <ul className="space-y-1">
                {section.groups.map((group) => (
                  <li key={group.id}>
                    <button
                      type="button"
                      className={`w-full rounded border px-2 py-2 text-left ${
                        selectedId === group.id
                          ? "border-blue-300 bg-blue-50"
                          : "border-gray-200 hover:bg-gray-50"
                      }`}
                      onClick={() => onSelect(group.id)}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-gray-900">
                          {group.name}
                          {(group.open_task_count ?? 0) > 0 && (
                            <span
                              className="ml-1.5 rounded bg-sky-100 px-1 text-[10px] font-medium text-sky-800"
                              title="Open tasks"
                            >
                              ☐ {group.open_task_count}
                            </span>
                          )}
                        </p>
                        <span
                          className={`rounded px-2 py-0.5 text-[11px] font-semibold uppercase ${statusClassName(group.status)}`}
                        >
                          {group.status}
                        </span>
                      </div>
                      {(group.tags ?? []).length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {(group.tags ?? []).map((chip) => (
                            <TagChipView key={chip.id} chip={chip} />
                          ))}
                        </div>
                      )}
                      <div className="mt-1 flex items-baseline justify-between gap-3">
                        <p className="text-xs text-gray-500">
                          #{group.id} · Opened {formatDateTime(group.opened_at)}
                        </p>
                        {group.total_pnl != null && (
                          <span
                            className={`shrink-0 text-xs font-semibold ${
                              group.total_pnl >= 0
                                ? "text-emerald-700"
                                : "text-red-700"
                            }`}
                          >
                            {fmt.masked(
                              group.total_pnl.toLocaleString(undefined, {
                                style: "currency",
                                currency: "USD",
                              }),
                            )}
                          </span>
                        )}
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        {!loading && sections.length === 0 && (
          <li className="rounded border border-dashed border-gray-300 px-2 py-3 text-xs text-gray-500">
            {!strategy
              ? "Select a strategy to view trade groups."
              : (groups ?? []).length === 0
                ? "No trade groups for this strategy yet."
                : `No ${filter === "all" ? "" : filter + " "}trade groups for this strategy.`}
          </li>
        )}
      </ul>

      {/* Divider — drag to resize the Trade Groups pane, double-click to
          reset. Hidden below `xl` where the panes stack. */}
      {!focusActive && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize trade groups list"
          onPointerDown={column.onHandlePointerDown}
          onDoubleClick={column.reset}
          title="Drag to resize · double-click to reset"
          className="group absolute -right-4 top-0 z-10 hidden h-full w-4 cursor-col-resize items-center justify-center xl:flex"
        >
          <div
            className={`h-10 w-1 rounded-full transition-colors ${
              column.isDragging
                ? "bg-blue-400"
                : "bg-gray-200 group-hover:bg-blue-300"
            }`}
          />
        </div>
      )}
    </div>
  );
}
