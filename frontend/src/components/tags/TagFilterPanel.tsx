// The search filters: "All of", "Any of", and "Exclude" tag lists, plus the
// toggle that includes tags on closed positions.

import { TagInput } from "../TagChips";
import { normalizeTagValue } from "../../lib/tags";

function FilterRow({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="w-16 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </span>
      {values.map((value) => (
        <span
          key={value}
          className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2 py-0.5 text-xs"
        >
          {value}
          <button
            type="button"
            onClick={() => onChange(values.filter((v) => v !== value))}
            className="text-gray-400 hover:text-red-600"
            aria-label={`Remove ${value}`}
          >
            ×
          </button>
        </span>
      ))}
      <TagInput
        autoFocus={false}
        placeholder="tag…"
        onPick={(value) => {
          const normalized = normalizeTagValue(value);
          if (!values.includes(normalized)) onChange([...values, normalized]);
        }}
      />
    </div>
  );
}

export default function TagFilterPanel({
  all,
  any,
  none,
  includeEnded,
  onChange,
  onIncludeEnded,
}: {
  all: string[];
  any: string[];
  none: string[];
  includeEnded: boolean;
  onChange: (key: "all" | "any" | "none", values: string[]) => void;
  onIncludeEnded: (include: boolean) => void;
}) {
  return (
    <div className="space-y-1.5 rounded border border-gray-200 bg-white p-3">
      <FilterRow
        label="All of"
        values={all}
        onChange={(v) => onChange("all", v)}
      />
      <FilterRow
        label="Any of"
        values={any}
        onChange={(v) => onChange("any", v)}
      />
      <FilterRow
        label="Exclude"
        values={none}
        onChange={(v) => onChange("none", v)}
      />
      <label className="flex items-center gap-1 pl-16 text-xs text-gray-500">
        <input
          type="checkbox"
          checked={includeEnded}
          onChange={(event) => onIncludeEnded(event.target.checked)}
        />
        Include tags on closed positions
      </label>
    </div>
  );
}
