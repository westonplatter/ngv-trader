// The blue bar that appears once at least one order is selected: add or
// remove a tag across the selection, or clear it.

import { TagInput } from "../TagChips";
import type { BulkTagging } from "./useBulkTagging";

export default function BulkTagBar({ bulk }: { bulk: BulkTagging }) {
  const count = bulk.selectedKeys.size;
  if (count === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-3 rounded border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-900">
      <span className="font-semibold">
        {count} order{count === 1 ? "" : "s"} selected
      </span>
      <span className="inline-flex items-center gap-1">
        Add tag
        <TagInput
          autoFocus={false}
          placeholder="Add tag…"
          onPick={(value) => void bulk.apply("add", value)}
        />
      </span>
      <span className="inline-flex items-center gap-1">
        Remove tag
        <TagInput
          autoFocus={false}
          placeholder="Remove tag…"
          onPick={(value) => void bulk.apply("remove", value)}
        />
      </span>
      <button
        type="button"
        onClick={bulk.clear}
        className="text-blue-700 underline"
      >
        Clear
      </button>
      {bulk.message && <span>{bulk.message}</span>}
    </div>
  );
}
