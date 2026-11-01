// The left column: the tag catalog with an "Archived" toggle, a box to create a
// tag, and one row per tag. Clicking a row searches for that tag.

import { TagInput } from "../TagChips";
import type { Tag } from "../../types/tags";
import TagRow from "./TagRow";

export default function TagCatalogPane({
  tags,
  showArchived,
  onShowArchived,
  onCreate,
  selectedValue,
  onSelect,
  onChanged,
}: {
  tags: Tag[];
  showArchived: boolean;
  onShowArchived: (show: boolean) => void;
  onCreate: (value: string) => void;
  /** Normalized value of the one tag the search is filtered to, if any. */
  selectedValue: string | null;
  onSelect: (tag: Tag) => void;
  onChanged: () => void;
}) {
  return (
    <aside className="w-72 shrink-0 space-y-2 overflow-y-auto rounded border border-gray-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-800">Tags</h2>
        <label className="flex items-center gap-1 text-xs text-gray-500">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => onShowArchived(event.target.checked)}
          />
          Archived
        </label>
      </div>
      <TagInput autoFocus={false} placeholder="New tag…" onPick={onCreate} />
      {tags.length === 0 && (
        <p className="text-xs text-gray-500">
          No tags yet. Add one here or from any trade, position, group, or task.
        </p>
      )}
      <ul className="space-y-0.5">
        {tags.map((tag) => (
          <TagRow
            key={tag.id}
            tag={tag}
            tags={tags}
            selected={selectedValue === tag.normalized_value}
            onSelect={() => onSelect(tag)}
            onChanged={onChanged}
          />
        ))}
      </ul>
    </aside>
  );
}
