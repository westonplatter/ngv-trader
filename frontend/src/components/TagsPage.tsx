// Tags page: the tag catalog (rename, recolor, merge, archive) and a search of
// tagged items by all / any / exclude, tabbed by kind. No P&L or other
// aggregates — tags are sticky notes, not a reporting dimension.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { TagChipView, TagInput } from "./TagChips";
import {
  type Tag,
  type TagEntityType,
  type TaggedItem,
  isAgent,
  normalizeTagValue,
  tagsApi,
} from "../lib/tags";

type Tab = "trades" | "positions" | "trade_groups" | "tasks";

const TABS: { id: Tab; label: string; types: TagEntityType[] }[] = [
  { id: "trades", label: "Trades", types: ["trade", "live_execution"] },
  { id: "positions", label: "Positions", types: ["position"] },
  { id: "trade_groups", label: "Trade groups", types: ["trade_group"] },
  { id: "tasks", label: "Tasks", types: ["task"] },
];

function readList(params: URLSearchParams, key: string): string[] {
  return (params.get(key) ?? "").split(",").filter(Boolean);
}

function formatWhen(value: unknown): string {
  if (typeof value !== "string") return "";
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? "" : new Date(parsed).toLocaleString();
}

function itemHref(item: TaggedItem): string | null {
  if (item.entity_type === "trade_group")
    return `/strategies?trade_group_id=${item.id}`;
  if (item.entity_type === "task") return `/tasks`;
  const symbol = item.details.symbol;
  if (item.entity_type === "position" && typeof symbol === "string")
    return `/positions`;
  if (typeof symbol === "string")
    return `/trades?symbol=${encodeURIComponent(symbol)}`;
  return null;
}

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

function TagRow({
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
  const [value, setValue] = useState(tag.value);
  const [color, setColor] = useState(tag.color ?? "#9ca3af");
  const [mergeInto, setMergeInto] = useState<number | "">("");
  const [error, setError] = useState<string | null>(null);
  const total = Object.values(tag.usage).reduce((a, b) => a + b, 0);

  const run = async (action: () => Promise<unknown>) => {
    try {
      setError(null);
      await action();
      setEditing(false);
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

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
          {isAgent(tag.created_by) && (
            <span className="rounded bg-violet-100 px-1 text-[9px] font-semibold uppercase text-violet-700">
              AI
            </span>
          )}
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
              onChange={(event) => setColor(event.target.value)}
              className="h-6 w-8"
              aria-label="Tag color"
            />
            <button
              type="button"
              onClick={() => run(() => tagsApi.patch(tag.id, { value, color }))}
              className="rounded bg-gray-900 px-2 py-0.5 text-white"
            >
              Save
            </button>
            {tag.color && (
              <button
                type="button"
                onClick={() =>
                  run(() => tagsApi.patch(tag.id, { color: null }))
                }
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
                setMergeInto(
                  event.target.value ? Number(event.target.value) : "",
                )
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
      )}
    </li>
  );
}

export default function TagsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tags, setTags] = useState<Tag[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [fetchedItems, setItems] = useState<TaggedItem[]>([]);
  const [includeEnded, setIncludeEnded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const all = readList(searchParams, "all");
  const any = readList(searchParams, "any");
  const none = readList(searchParams, "none");
  const tab = (searchParams.get("tab") as Tab | null) ?? "trades";

  // One update for several keys: react-router does not chain functional
  // setSearchParams updates made in the same tick, so the last would win.
  const setParams = (updates: Record<string, string[] | string>) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, values] of Object.entries(updates)) {
          const text = Array.isArray(values) ? values.join(",") : values;
          if (text) next.set(key, text);
          else next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  };
  const setParam = (key: string, values: string[] | string) =>
    setParams({ [key]: values });

  const loadTags = useCallback(() => {
    tagsApi
      .list(undefined, showArchived)
      .then((rows) =>
        setTags(
          [...rows].sort((a, b) =>
            a.value.localeCompare(b.value, undefined, { sensitivity: "base" }),
          ),
        ),
      )
      .catch((err: Error) => setError(err.message));
  }, [showArchived]);

  const filterKey = `${all.join(",")}|${any.join(",")}|${none.join(",")}|${includeEnded}`;
  const loadItems = useCallback(() => {
    // With no tag chosen there is nothing to search; the render shows a prompt.
    if (all.length === 0 && any.length === 0) return;
    tagsApi
      .search({ all, any, none, includeEnded })
      .then((result) => setItems(result.items))
      .catch((err: Error) => setError(err.message));
    // filterKey captures every input.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey]);

  useEffect(() => loadTags(), [loadTags]);
  useEffect(() => loadItems(), [loadItems]);

  const hasFilter = all.length > 0 || any.length > 0;
  const items = useMemo(
    () => (hasFilter ? fetchedItems : []),
    [hasFilter, fetchedItems],
  );
  const counts = useMemo(() => {
    const out: Record<Tab, number> = {
      trades: 0,
      positions: 0,
      trade_groups: 0,
      tasks: 0,
    };
    for (const t of TABS)
      out[t.id] = items.filter((item) =>
        t.types.includes(item.entity_type as TagEntityType),
      ).length;
    return out;
  }, [items]);
  const tabTypes = TABS.find((t) => t.id === tab)?.types ?? [];
  const visible = items.filter((item) =>
    tabTypes.includes(item.entity_type as TagEntityType),
  );

  return (
    <div className="flex h-full gap-4">
      <aside className="w-72 shrink-0 space-y-2 overflow-y-auto rounded border border-gray-200 bg-white p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">Tags</h2>
          <label className="flex items-center gap-1 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(event) => setShowArchived(event.target.checked)}
            />
            Archived
          </label>
        </div>
        <TagInput
          autoFocus={false}
          placeholder="New tag…"
          onPick={(value) =>
            void tagsApi
              .create(value)
              .then(loadTags)
              .catch((err: Error) => setError(err.message))
          }
        />
        {tags.length === 0 && (
          <p className="text-xs text-gray-500">
            No tags yet. Add one here or from any trade, position, group, or
            task.
          </p>
        )}
        <ul className="space-y-0.5">
          {tags.map((tag) => (
            <TagRow
              key={tag.id}
              tag={tag}
              tags={tags}
              selected={all.length === 1 && all[0] === tag.normalized_value}
              onSelect={() =>
                setParams({ all: [tag.normalized_value], any: [], none: [] })
              }
              onChanged={() => {
                loadTags();
                loadItems();
              }}
            />
          ))}
        </ul>
      </aside>

      <section className="min-w-0 flex-1 space-y-3">
        <div className="space-y-1.5 rounded border border-gray-200 bg-white p-3">
          <FilterRow
            label="All of"
            values={all}
            onChange={(v) => setParam("all", v)}
          />
          <FilterRow
            label="Any of"
            values={any}
            onChange={(v) => setParam("any", v)}
          />
          <FilterRow
            label="Exclude"
            values={none}
            onChange={(v) => setParam("none", v)}
          />
          <label className="flex items-center gap-1 pl-16 text-xs text-gray-500">
            <input
              type="checkbox"
              checked={includeEnded}
              onChange={(event) => setIncludeEnded(event.target.checked)}
            />
            Include tags on closed positions
          </label>
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex gap-1 border-b border-gray-200">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setParam("tab", t.id === "trades" ? "" : t.id)}
              className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
                tab === t.id
                  ? "border-blue-600 font-medium text-blue-700"
                  : "border-transparent text-gray-600 hover:text-gray-900"
              }`}
            >
              {t.label}{" "}
              <span className="text-xs text-gray-400">{counts[t.id]}</span>
            </button>
          ))}
        </div>

        {all.length === 0 && any.length === 0 ? (
          <p className="text-sm text-gray-500">
            Pick a tag on the left, or add tags to “All of” / “Any of”.
          </p>
        ) : visible.length === 0 ? (
          <p className="text-sm text-gray-500">Nothing here matches.</p>
        ) : (
          <table className="min-w-full border-collapse text-sm">
            <tbody>
              {visible.map((item) => {
                const href = itemHref(item);
                const key = `${item.entity_type}:${item.id ?? item.ib_exec_id ?? `${item.account_id}-${item.con_id}`}`;
                return (
                  <tr key={key} className="border-b border-gray-100">
                    <td className="whitespace-nowrap px-2 py-1.5 font-medium text-gray-800">
                      {href ? (
                        <Link to={href} className="hover:underline">
                          {item.label}
                        </Link>
                      ) : (
                        item.label
                      )}
                      {item.entity_type === "live_execution" && (
                        <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">
                          unsettled
                        </span>
                      )}
                      {item.entity_type === "position" &&
                        item.details.open === false && (
                          <span className="ml-1 rounded bg-gray-100 px-1 text-[10px] text-gray-600">
                            closed
                          </span>
                        )}
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-xs text-gray-500">
                      {formatWhen(item.details.executed_at)}
                      {typeof item.details.status === "string" &&
                        item.details.status}
                      {typeof item.details.strategy === "string" &&
                        ` · ${item.details.strategy}`}
                    </td>
                    <td className="px-2 py-1.5">
                      <span className="inline-flex flex-wrap gap-1">
                        {item.tags.map((chip) => (
                          <TagChipView key={chip.id} chip={chip} />
                        ))}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
