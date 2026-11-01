// One tag in the catalog: its color dot, name, usage count, and an Edit toggle
// that opens the inline editor.

import { useState } from "react";
import AgentBadge from "../AgentBadge";
import type { Tag } from "../../types/tags";
import TagEditPanel from "./TagEditPanel";

export default function TagRow({
  tag,
  tags,
  selected,
  onSelect,
  onChanged,
}: {
  tag: Tag;
  tags: Tag[];
  selected: boolean;
  onSelect: () => void;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const total = Object.values(tag.usage).reduce((a, b) => a + b, 0);

  return (
    <li
      className={`rounded px-2 py-1.5 ${selected ? "bg-blue-50" : "hover:bg-gray-50"}`}
    >
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onSelect}
          className="flex min-w-0 items-center gap-2 text-left"
          title="Search items with this tag"
        >
          <span
            className="h-2.5 w-2.5 shrink-0 rounded-full"
            style={{ backgroundColor: tag.color ?? "#d1d5db" }}
          />
          <span
            className={`truncate text-sm ${tag.archived_at ? "text-gray-400 line-through" : "text-gray-800"}`}
          >
            {tag.value}
          </span>
          <AgentBadge createdBy={tag.created_by} />
        </button>
        <span className="flex shrink-0 items-center gap-2 text-xs text-gray-500">
          <span title={JSON.stringify(tag.usage)}>{total}</span>
          <button
            type="button"
            onClick={() => setEditing((v) => !v)}
            className="text-gray-400 hover:text-gray-700"
          >
            {editing ? "Close" : "Edit"}
          </button>
        </span>
      </div>
      {editing && (
        <TagEditPanel
          tag={tag}
          tags={tags}
          onDone={() => {
            setEditing(false);
            onChanged();
          }}
        />
      )}
    </li>
  );
}
