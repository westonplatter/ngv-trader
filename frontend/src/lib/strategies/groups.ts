// Pure list logic behind the Strategies workspace: how the strategy and
// trade-group lists are ordered, filtered, and sectioned, and how a selection
// survives a reload.
//
// Kept out of the components so the behavior has a bun test: the repo has no
// DOM harness, so anything worth asserting must be a function over plain data.

import type { Strategy } from "../../types/strategies";
import type { TradeGroup } from "../../types/tradeGroups";

export type GroupStatus = TradeGroup["status"];

export const GROUP_STATUSES: GroupStatus[] = ["open", "closed", "archived"];

export const STATUS_LABELS: Record<GroupStatus, string> = {
  open: "Open",
  closed: "Closed",
  archived: "Archived",
};

export type GroupFilter = "active" | "closed" | "archived" | "all";

export const GROUP_FILTERS: { value: GroupFilter; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "closed", label: "Closed" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

export type GroupSort =
  | "name"
  | "name_grouped"
  | "opened_at"
  | "opened_at_grouped";

export const GROUP_SORTS: { value: GroupSort; label: string }[] = [
  { value: "name", label: "A–Z" },
  { value: "name_grouped", label: "A–Z Grouped" },
  { value: "opened_at", label: "Opened" },
  { value: "opened_at_grouped", label: "Opened Grouped" },
];

// The "*_grouped" sorts split the list into Open / Closed / Archived sections;
// the plain sorts render one flat list. The sort key (name vs opened_at) is the
// same in both.
export function sortIsGrouped(sort: GroupSort): boolean {
  return sort.endsWith("_grouped");
}

export function sortKey(sort: GroupSort): "name" | "opened_at" {
  return sort.startsWith("opened_at") ? "opened_at" : "name";
}

export interface GroupSection {
  // null for the single unlabeled block of a flat sort.
  status: GroupStatus | null;
  groups: TradeGroup[];
}

// Rendered as sections. The "*_grouped" sorts split into Open → Closed →
// Archived blocks (each with a colored header); the plain sorts render a
// single flat block with `status: null` (no header). A specific status filter
// narrows to that one status; "All" shows every non-empty status. Within a
// block, order by the sort key (name or opened_at).
export function groupSections(
  groups: TradeGroup[],
  filter: GroupFilter,
  sort: GroupSort,
): GroupSection[] {
  const key = sortKey(sort);
  const sortGroups = (list: TradeGroup[]) =>
    [...list].sort((a, b) => {
      if (key === "opened_at") {
        // Most recently opened first; fall back to name for equal timestamps.
        const diff = Date.parse(b.opened_at) - Date.parse(a.opened_at);
        if (diff !== 0) return diff;
      }
      return a.name.localeCompare(b.name, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });
  const statuses: GroupStatus[] =
    filter === "all" ? GROUP_STATUSES : [filter === "active" ? "open" : filter];
  const inScope = groups.filter((group) => statuses.includes(group.status));

  if (!sortIsGrouped(sort)) {
    // Flat: one unlabeled block sorted across all in-scope statuses.
    return inScope.length ? [{ status: null, groups: sortGroups(inScope) }] : [];
  }
  return statuses
    .map((status) => ({
      status,
      groups: sortGroups(inScope.filter((group) => group.status === status)),
    }))
    .filter((section) => section.groups.length > 0);
}

// Strategies list order: by name, case-insensitively.
export function sortStrategies(raw: Strategy[]): Strategy[] {
  return [...raw].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: "base" }),
  );
}

export function parseIdParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

// Keep the current selection while it is still in the list; otherwise fall
// back to the first entry, or null when the list is empty.
export function resolveSelection<T extends { id: number }>(
  current: number | null,
  items: T[],
): number | null {
  if (items.length === 0) return null;
  if (current != null && items.some((item) => item.id === current))
    return current;
  return items[0].id;
}
