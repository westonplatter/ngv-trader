// Pure rules for the trade-group picker: what to search for, how to merge the
// recommended groups into the full list, where the popover sits, and how the
// keyboard highlight moves. No React and no network, so each is unit-tested. The
// interaction itself is in components/tradeGroupSearch/.

import type { TradeGroupResult } from "../types/tradeGroups";

// How many recommended groups float to the top of the list.
export const RECOMMENDED_COUNT = 2;

// The contract's symbol root — the first whitespace-delimited token of the
// display name. Works for shares ("GLD" → "GLD") and options
// ("GLD Dec31'25 412 CALL" → "GLD"), so it can seed a recommended-group search.
export function contractSymbol(display: string | null): string | null {
  if (!display) return null;
  const token = display.trim().split(/\s+/)[0];
  return token ? token.toUpperCase() : null;
}

// The `instrument` filter is a Postgres case-insensitive regex, so a symbol with
// a metacharacter in it ("BRK.B") has to be escaped before it becomes a pattern.
export function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function withListDefaults(params: URLSearchParams): URLSearchParams {
  params.set("limit", "20");
  params.set("status", "open");
  return params;
}

// What the operator types: a free-text match on group name / strategy value.
export function textSearchParams(text: string): URLSearchParams {
  const params = new URLSearchParams();
  if (text.trim()) params.set("q", text.trim());
  return withListDefaults(params);
}

// What we recommend before they type: groups that already hold fills on this
// underlying, which is the signal `q` cannot see — a group named "Nat Gas
// Winter Spread" is where NG was grouped last time, and no text match finds it.
// `instrument` matches the derived underlying root of a group's assigned
// executions, falling back to its name (so a group opened today with no fills
// yet still surfaces). Anchoring at the start is what keeps that name fallback
// from firing on any substring — unanchored, "NG" recommends "Gold Holdings"
// and "Long Delta".
export function recommendedSearchParams(symbol: string): URLSearchParams {
  return withListDefaults(
    new URLSearchParams({ instrument: `^${escapeRegex(symbol)}` }),
  );
}

// The opening list: the top recommended groups first, then every other open
// group (recency order) with the shown recommendations de-duped out.
export function mergeRecommended(
  recommended: TradeGroupResult[],
  all: TradeGroupResult[],
): TradeGroupResult[] {
  const top = recommended.slice(0, RECOMMENDED_COUNT);
  const shown = new Set(top.map((g) => g.id));
  return [...top, ...all.filter((g) => !shown.has(g.id))];
}

// Move the keyboard highlight one step, wrapping at both ends. An empty list
// has nothing to highlight.
export function stepHighlight(
  index: number,
  delta: 1 | -1,
  length: number,
): number {
  if (length === 0) return 0;
  return (index + delta + length) % length;
}

export interface PopoverPosition {
  top: number;
  left: number;
  width: number;
  flipUp: boolean;
}

const FLIP_THRESHOLD_PX = 260;
const MIN_WIDTH_PX = 240;

// Where the results list sits relative to the search input: below it, or above
// it when there is less than FLIP_THRESHOLD_PX of room underneath.
export function popoverPosition(
  rect: { top: number; bottom: number; left: number; width: number },
  viewportHeight: number,
): PopoverPosition {
  const flipUp = viewportHeight - rect.bottom < FLIP_THRESHOLD_PX;
  return {
    top: flipUp ? rect.top : rect.bottom + 4,
    left: rect.left,
    // Match the trigger cell's rendered width (the dynamically sized Trade Group
    // column), with a floor so the list is never uncomfortably narrow.
    width: Math.max(rect.width, MIN_WIDTH_PX),
    flipUp,
  };
}
