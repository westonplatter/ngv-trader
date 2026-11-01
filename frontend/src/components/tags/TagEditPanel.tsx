// The inline editor under a tag row: rename, recolor, merge into another tag,
// and archive. Mounted only while open, so each opening starts from the tag's
// current values.

import { useState } from "react";
import { useAsyncAction } from "../../hooks/useAsyncAction";
import { tagsApi } from "../../lib/tags";
import type { Tag } from "../../types/tags";

export default function TagEditPanel({
  tag,
  tags,
  onDone,
}: {
  tag: Tag;
  tags: Tag[];
  /** Called after any change succeeds. */
  onDone: () => void;
}) {
  const [value, setValue] = useState(tag.value);
  const [color, setColor] = useState(tag.color ?? "#9ca3af");
  // An uncolored tag stays uncolored unless the picker was actually used.
  const [colorTouched, setColorTouched] = useState(false);
  const [mergeInto, setMergeInto] = useState<number | "">("");
  const { run, error } = useAsyncAction(onDone);

  return (
    <div className="mt-2 space-y-2 rounded border border-gray-200 bg-white p-2 text-xs">
      <div className="flex items-center gap-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          className="flex-1 rounded border border-gray-300 px-1.5 py-0.5"
        />
        <input
          type="color"
          value={color}
          onChange={(event) => {
            setColor(event.target.value);
            setColorTouched(true);
          }}
          className="h-6 w-8"
          aria-label="Tag color"
        />
        <button
          type="button"
          onClick={() =>
            run(() =>
              tagsApi.patch(
                tag.id,
                colorTouched ? { value, color } : { value },
              ),
            )
          }
          className="rounded bg-gray-900 px-2 py-0.5 text-white"
        >
          Save
        </button>
        {tag.color && (
          <button
            type="button"
            onClick={() => run(() => tagsApi.patch(tag.id, { color: null }))}
            className="text-gray-500 underline"
          >
            No color
          </button>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span>Merge into</span>
        <select
          value={mergeInto}
          onChange={(event) =>
            setMergeInto(event.target.value ? Number(event.target.value) : "")
          }
          className="flex-1 rounded border border-gray-300 px-1 py-0.5"
        >
          <option value="">—</option>
          {tags
            .filter((other) => other.id !== tag.id)
            .map((other) => (
              <option key={other.id} value={other.id}>
                {other.value}
              </option>
            ))}
        </select>
        <button
          type="button"
          disabled={mergeInto === ""}
          onClick={() =>
            mergeInto !== "" &&
            window.confirm(
              `Merge "${tag.value}" into the selected tag? This deletes "${tag.value}".`,
            ) &&
            run(() => tagsApi.merge(tag.id, mergeInto))
          }
          className="rounded border border-gray-300 px-2 py-0.5 disabled:opacity-40"
        >
          Merge
        </button>
      </div>
      <button
        type="button"
        onClick={() =>
          run(() =>
            tag.archived_at
              ? tagsApi.unarchive(tag.id)
              : tagsApi.archive(tag.id),
          )
        }
        className="text-gray-600 underline"
      >
        {tag.archived_at ? "Unarchive" : "Archive"}
      </button>
      {error && <p className="text-red-600">{error}</p>}
    </div>
  );
}
