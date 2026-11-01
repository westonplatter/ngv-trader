// Pure logic for the Tags page: the result tabs, the URL filter parameters, and
// the small formatting and sorting rules. No React and no network, so each rule
// is unit-tested. The page wiring is in components/tags/.

import type { Tag, TagEntityType, TaggedItem } from "../types/tags";

export type Tab = "trades" | "positions" | "trade_groups" | "tasks";

export const TABS: { id: Tab; label: string; types: TagEntityType[] }[] = [
  { id: "trades", label: "Trades", types: ["trade", "live_execution"] },
  { id: "positions", label: "Positions", types: ["position"] },
  { id: "trade_groups", label: "Trade groups", types: ["trade_group"] },
  { id: "tasks", label: "Tasks", types: ["task"] },
];

// A comma-separated URL value as a list; empty pieces are dropped.
export function splitList(text: string): string[] {
  return text.split(",").filter(Boolean);
}

// The active tab, from the `tab` URL value. The Trades tab is the default and is
// stored as no value at all.
export function parseTab(raw: string | null): Tab {
  return (raw as Tab | null) ?? "trades";
}

// Apply several key updates to a copy of the URL params. A list is joined with
// commas; an empty value removes the key so the URL stays short.
export function applyParamUpdates(
  prev: URLSearchParams,
  updates: Record<string, string[] | string>,
): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const [key, values] of Object.entries(updates)) {
    const text = Array.isArray(values) ? values.join(",") : values;
    if (text) next.set(key, text);
    else next.delete(key);
  }
  return next;
}

// Tags in the catalog's display order: by value, ignoring case and accents.
export function sortTagsByValue(rows: Tag[]): Tag[] {
  return [...rows].sort((a, b) =>
    a.value.localeCompare(b.value, undefined, { sensitivity: "base" }),
  );
}

// The items shown under one tab.
export function itemsForTab(items: TaggedItem[], tab: Tab): TaggedItem[] {
  const types: string[] = TABS.find((t) => t.id === tab)?.types ?? [];
  return items.filter((item) => types.includes(item.entity_type));
}

// How many items each tab would show, for the counts beside the tab names.
export function countByTab(items: TaggedItem[]): Record<Tab, number> {
  const out: Record<Tab, number> = {
    trades: 0,
    positions: 0,
    trade_groups: 0,
    tasks: 0,
  };
  for (const t of TABS) out[t.id] = itemsForTab(items, t.id).length;
  return out;
}

// An ISO timestamp as a local date and time; anything else is blank.
export function formatWhen(value: unknown): string {
  if (typeof value !== "string") return "";
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? "" : new Date(parsed).toLocaleString();
}
