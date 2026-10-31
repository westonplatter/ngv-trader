// Inline tag editor: the item's chips, × to remove, and a type-ahead to add.
// Enter on text that matches no tag creates it. Agent-applied chips carry a
// small marker so a person can tell what an LLM agent did.

import { useEffect, useRef, useState } from "react";
import AgentBadge from "./AgentBadge";
import { useAsyncAction } from "../hooks/useAsyncAction";
import {
  type ItemRef,
  type Tag,
  type TagChip,
  agentName,
  isAgent,
  normalizeTagValue,
  tagsApi,
} from "../lib/tags";

export function TagChipView({
  chip,
  onRemove,
}: {
  chip: TagChip;
  onRemove?: () => void;
}) {
  const agent = isAgent(chip.created_by);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium text-gray-800"
      style={{
        borderColor: chip.color ?? "#d1d5db",
        backgroundColor: chip.color ? `${chip.color}22` : "#f9fafb",
      }}
      title={
        agent
          ? `Applied by agent ${agentName(chip.created_by)}`
          : "Applied by you"
      }
    >
      <AgentBadge createdBy={chip.created_by} what="Applied" />
      {chip.value}
      {onRemove && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
          className="text-gray-400 hover:text-red-600"
          aria-label={`Remove tag ${chip.value}`}
        >
          ×
        </button>
      )}
    </span>
  );
}

// Type-ahead input that resolves to a tag name (existing or new). Shared by the
// inline editor and the bulk "Add tag…" control.
export function TagInput({
  onPick,
  onCancel,
  placeholder = "Add tag…",
  exclude = [],
  autoFocus = true,
}: {
  onPick: (value: string) => void;
  onCancel?: () => void;
  placeholder?: string;
  exclude?: number[];
  autoFocus?: boolean;
}) {
  const [text, setText] = useState("");
  const [suggestions, setSuggestions] = useState<Tag[]>([]);
  const [active, setActive] = useState(0);
  const [navigated, setNavigated] = useState(false);
  // Suggestions show only while the input has focus, so several inputs on one
  // page never open their lists at once.
  const [focused, setFocused] = useState(autoFocus);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  useEffect(() => {
    let cancelled = false;
    const handle = window.setTimeout(() => {
      tagsApi
        .list(text || undefined)
        .then((tags) => {
          if (!cancelled)
            setSuggestions(
              tags.filter((tag) => !exclude.includes(tag.id)).slice(0, 8),
            );
        })
        .catch(() => {
          if (!cancelled) setSuggestions([]);
        });
    }, 120);
    return () => {
      cancelled = true;
      window.clearTimeout(handle);
    };
    // exclude is compared by content; a new array each render must not refetch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, exclude.join(",")]);

  const exact = suggestions.find(
    (tag) => tag.normalized_value === normalizeTagValue(text),
  );
  const pick = (value: string) => {
    if (!normalizeTagValue(value)) return;
    onPick(value);
    setText("");
  };

  return (
    <span className="relative inline-block">
      <input
        ref={inputRef}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setActive(0);
          setNavigated(false);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") onCancel?.();
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((i) => Math.min(i + 1, suggestions.length - 1));
            setNavigated(true);
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((i) => Math.max(i - 1, 0));
            setNavigated(true);
          }
          if (event.key === "Enter") {
            event.preventDefault();
            // A highlighted suggestion wins; otherwise an exact match, else the
            // typed text becomes a new tag.
            const chosen =
              navigated || !text.trim() ? suggestions[active] : (exact ?? null);
            pick(chosen ? chosen.value : text);
          }
        }}
        onFocus={() => setFocused(true)}
        onBlur={() =>
          window.setTimeout(() => {
            setFocused(false);
            onCancel?.();
          }, 150)
        }
        placeholder={placeholder}
        className="w-32 rounded border border-gray-300 px-1.5 py-0.5 text-xs"
      />
      {focused && (suggestions.length > 0 || (text.trim() && !exact)) && (
        <span className="absolute left-0 top-full z-30 mt-1 block w-56 rounded border border-gray-200 bg-white py-1 text-xs shadow-lg">
          {suggestions.map((tag, index) => (
            <button
              key={tag.id}
              type="button"
              onMouseDown={(event) => {
                event.preventDefault();
                pick(tag.value);
              }}
              className={`flex w-full items-center justify-between px-2 py-1 text-left ${
                index === active ? "bg-blue-50" : "hover:bg-gray-50"
              }`}
            >
              <span>{tag.value}</span>
              <span className="text-gray-400">
                {Object.values(tag.usage).reduce((a, b) => a + b, 0)}
              </span>
            </button>
          ))}
          {text.trim() && !exact && (
            <span className="block border-t border-gray-100 px-2 py-1 text-gray-500">
              Enter creates “{text.trim()}”
            </span>
          )}
        </span>
      )}
    </span>
  );
}

export default function TagChips({
  item,
  tags,
  onChanged,
  readOnly = false,
}: {
  item: ItemRef | null;
  tags: TagChip[];
  onChanged: () => void;
  readOnly?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const { run, error } = useAsyncAction(onChanged);

  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {tags.map((chip) => (
        <TagChipView
          key={chip.id}
          chip={chip}
          onRemove={
            readOnly || !item
              ? undefined
              : () => run(() => tagsApi.detach([chip.id], [item]))
          }
        />
      ))}
      {!readOnly &&
        item &&
        (adding ? (
          <TagInput
            exclude={tags.map((chip) => chip.id)}
            onPick={(value) => run(() => tagsApi.attach([value], [item]))}
            onCancel={() => setAdding(false)}
          />
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="rounded-full border border-dashed border-gray-300 px-1.5 text-[11px] text-gray-500 hover:border-gray-500 hover:text-gray-800"
            title="Add tag"
          >
            + tag
          </button>
        ))}
      {error && <span className="text-[11px] text-red-600">{error}</span>}
    </span>
  );
}
