// Left sidebar: the saved structures and the Save / Save As / Delete actions.

import type { SavedStructures } from "./useSavedStructures";

export default function SavedStructuresSidebar({
  saved,
  onLoad,
  onSave,
  onSaveAs,
  onDelete,
}: {
  saved: SavedStructures;
  onLoad: (id: number) => void;
  onSave: () => void;
  onSaveAs: () => void;
  onDelete: () => void;
}) {
  const { structures, loadedId, status, feedback } = saved;
  return (
    <div className="w-56 shrink-0">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
        Structures
      </h2>
      <div className="space-y-1 mb-3">
        {structures.length === 0 && (
          <p className="text-xs text-gray-400">No saved structures</p>
        )}
        {structures.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onLoad(s.id)}
            className={`w-full text-left px-2 py-1.5 rounded text-sm truncate ${
              loadedId === s.id
                ? "bg-blue-100 text-blue-800 font-medium"
                : "text-gray-700 hover:bg-gray-100"
            }`}
            title={s.name}
          >
            <span className="text-gray-400 text-xs mr-1">/{s.instrument}</span>
            {s.name}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={onSaveAs}
          className="text-xs border border-blue-500 text-blue-600 rounded px-2 py-1 hover:bg-blue-50"
        >
          Save As...
        </button>
        {loadedId != null && (
          <>
            <button
              type="button"
              onClick={onSave}
              disabled={status === "pending"}
              className="text-xs bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {status === "pending" ? "Saving..." : "Save"}
            </button>
            <button
              type="button"
              onClick={onDelete}
              className="text-xs border border-red-400 text-red-500 rounded px-2 py-1 hover:bg-red-50"
            >
              Delete
            </button>
            {feedback && (
              <p
                aria-live="polite"
                className={`text-[11px] leading-tight ${
                  status === "error" ? "text-red-600" : "text-gray-500"
                }`}
              >
                {feedback}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
