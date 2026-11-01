// Column 1 of the workspace: the strategy list with its archive toggle, the
// inline "+ New" form, and the drag handle that resizes the column.

import { useState } from "react";
import type { ResizableColumn } from "../../hooks/useResizableColumn";
import { errorMessage } from "../../lib/api";
import type { Strategy } from "../../types/strategies";

export default function StrategyListPane({
  strategies,
  selectedId,
  onSelect,
  showArchived,
  onShowArchived,
  onCreate,
  onSetArchived,
  column,
  focusActive,
  onError,
}: {
  strategies: Strategy[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  showArchived: boolean;
  onShowArchived: (value: boolean) => void;
  onCreate: (name: string) => Promise<void>;
  onSetArchived: (strategy: Strategy, archived: boolean) => Promise<void>;
  column: ResizableColumn;
  focusActive: boolean;
  onError: (message: string) => void;
}) {
  const [showNew, setShowNew] = useState(false);
  const [newValue, setNewValue] = useState("");

  const submit = () => {
    onCreate(newValue)
      .then(() => {
        setNewValue("");
        setShowNew(false);
      })
      .catch((err: unknown) =>
        onError(errorMessage(err, "Failed to create strategy.")),
      );
  };

  return (
    // Collapses to zero width in focus mode. The card padding/border are
    // dropped while collapsed so the 0fr track reaches true zero (padding+border
    // are its min-content floor). `inert` while collapsed keeps its hidden
    // controls out of the tab order (overflow-hidden alone does not).
    <section
      inert={focusActive}
      className={`relative flex min-h-0 min-w-0 flex-col ${
        focusActive
          ? "overflow-hidden border-0 p-0"
          : "rounded border border-gray-200 bg-white p-3"
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold">Strategy List</h3>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => onShowArchived(event.target.checked)}
            />
            Show archived
          </label>
          <button
            type="button"
            onClick={() => setShowNew(!showNew)}
            className="rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-600 hover:bg-gray-50"
          >
            {showNew ? "Cancel" : "+ New"}
          </button>
        </div>
      </div>

      {showNew && (
        <div className="mb-3 space-y-2 rounded border border-dashed border-gray-300 p-2">
          <input
            value={newValue}
            onChange={(event) => setNewValue(event.target.value)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
            placeholder="Strategy name"
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
          />
          <button
            type="button"
            onClick={submit}
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
                  selectedId === strategy.id
                    ? "border-blue-300 bg-blue-50 text-blue-900"
                    : "border-gray-200 hover:bg-gray-50"
                } ${isArchived ? "opacity-60" : ""}`}
                onClick={() => onSelect(strategy.id)}
              >
                <p className="font-medium">
                  {strategy.name}
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
                  onSetArchived(strategy, !isArchived).catch((err: unknown) =>
                    onError(errorMessage(err, "Failed to update strategy.")),
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

      {/* Divider — drag to resize the Strategy List pane, double-click to
          reset. Hidden below `lg` where the layout stacks vertically. */}
      {!focusActive && (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize strategy list"
          onPointerDown={column.onHandlePointerDown}
          onDoubleClick={column.reset}
          title="Drag to resize · double-click to reset"
          className="group absolute -right-4 top-0 z-10 hidden h-full w-4 cursor-col-resize items-center justify-center lg:flex"
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
    </section>
  );
}
