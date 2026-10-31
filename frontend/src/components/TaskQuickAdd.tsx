// Task badge plus a "+ task" shortcut for a row: shows the open-task count
// (linking to the Tasks page) and creates a task linked to the row's item.

import { useState } from "react";
import { Link } from "react-router-dom";
import { tasksApi } from "../lib/tags";
import type { ItemRef } from "../types/tags";

export default function TaskQuickAdd({
  item,
  openCount,
  onCreated,
  tasksHref,
}: {
  item: ItemRef | null;
  openCount: number;
  onCreated: () => void;
  // Where the badge links; defaults to the Tasks page.
  tasksHref?: string;
}) {
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!item || !title.trim()) return;
    try {
      await tasksApi.create({ title: title.trim(), links: [item] });
      setTitle("");
      setAdding(false);
      setError(null);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <span className="inline-flex items-center gap-1">
      {openCount > 0 && (
        <Link
          to={tasksHref ?? "/tasks"}
          className="rounded bg-sky-100 px-1.5 py-0.5 text-[11px] font-medium text-sky-800 hover:bg-sky-200"
          title={`${openCount} open task${openCount === 1 ? "" : "s"}`}
        >
          ☐ {openCount}
        </Link>
      )}
      {item &&
        (adding ? (
          <input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void submit();
              if (event.key === "Escape") setAdding(false);
            }}
            onBlur={() => !title.trim() && setAdding(false)}
            placeholder="New task…"
            className="w-36 rounded border border-gray-300 px-1.5 py-0.5 text-xs"
          />
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="rounded border border-dashed border-gray-300 px-1.5 text-[11px] text-gray-500 hover:border-gray-500 hover:text-gray-800"
            title="Add a task linked to this row"
          >
            + task
          </button>
        ))}
      {error && <span className="text-[11px] text-red-600">{error}</span>}
    </span>
  );
}
