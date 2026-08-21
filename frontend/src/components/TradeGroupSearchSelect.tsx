import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";
import { type TradeGroupResult, tradeGroupLabel } from "../lib/tradeGroups";

// `fetch` has no default timeout: a request the server accepts but never answers
// — an API restart dropping an in-flight connection, say — leaves its promise
// pending forever, so the picker would sit on "Searching..." with no way back.
// Bounding it turns that into an ordinary rejection the caller can recover from.
const SEARCH_TIMEOUT_MS = 8000;

// The contract's symbol root — the first whitespace-delimited token of the
// display name. Works for shares ("GLD" → "GLD") and options
// ("GLD Dec31'25 412 CALL" → "GLD"), so it can seed a recommended-group search
// (q=GLD matches a group named "GLD Rolling Diagonals").
function contractSymbol(display: string | null): string | null {
  if (!display) return null;
  const token = display.trim().split(/\s+/)[0];
  return token ? token.toUpperCase() : null;
}

/**
 * A searchable trade-group picker shared by the Positions and Trades tables.
 *
 * The caller supplies the trigger affordance via `renderTrigger` (e.g. a
 * "+ Assign" button or an assigned-group chip) and receives the chosen group
 * through `onSelect`. This component owns only the search interaction: opening
 * a popover, debounced querying of open trade groups, keyboard navigation, and
 * click-away / Esc dismissal. Assignment side effects stay with the caller.
 */
export default function TradeGroupSearchSelect({
  accountId,
  contractDisplayName,
  onSelect,
  disabled = false,
  renderTrigger,
}: {
  accountId: number;
  contractDisplayName: string | null;
  onSelect: (group: TradeGroupResult) => void | Promise<void>;
  disabled?: boolean;
  renderTrigger: (open: () => void) => React.ReactNode;
}) {
  const [mode, setMode] = useState<"display" | "search">("display");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<TradeGroupResult[]>([]);
  const [loading, setLoading] = useState(false);
  // A failed search is not an empty one: without this, a dropped request reads
  // as "No trade groups found" and invites creating a duplicate group.
  const [failed, setFailed] = useState(false);
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [dropdownPos, setDropdownPos] = useState<{
    top: number;
    left: number;
    width: number;
    flipUp: boolean;
  } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchVersionRef = useRef(0);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const updateDropdownPos = useCallback(() => {
    if (!inputRef.current) return;
    const rect = inputRef.current.getBoundingClientRect();
    const spaceBelow = window.innerHeight - rect.bottom;
    const flipUp = spaceBelow < 260;
    setDropdownPos({
      top: flipUp ? rect.top : rect.bottom + 4,
      left: rect.left,
      // Match the trigger cell's rendered width (the dynamically sized Tag Group
      // column), with a floor so the list is never uncomfortably narrow.
      width: Math.max(rect.width, 240),
      flipUp,
    });
  }, []);

  const searchGroups = useCallback(async (searchQuery: string) => {
    const params = new URLSearchParams({ limit: "20", status: "open" });
    if (searchQuery.trim()) params.set("q", searchQuery.trim());
    const response = await fetch(
      `${API_BASE_URL}/trade-groups?${params.toString()}`,
      { signal: AbortSignal.timeout(SEARCH_TIMEOUT_MS) },
    );
    if (!response.ok) {
      throw new Error(`Unable to search trade groups (${response.status})`);
    }
    return (await response.json()) as TradeGroupResult[];
  }, []);

  // Replace the result set and reset the keyboard highlight in one step, so we
  // don't need a separate effect that re-renders just to reset the index.
  const applyResults = useCallback((data: TradeGroupResult[]) => {
    setResults(data);
    setHighlightedIndex(0);
    setFailed(false);
  }, []);

  const applyFailure = useCallback(() => {
    setResults([]);
    setHighlightedIndex(0);
    setFailed(true);
  }, []);

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      const version = ++searchVersionRef.current;
      debounceRef.current = setTimeout(() => {
        setLoading(true);
        void searchGroups(value)
          .then((data) => {
            if (searchVersionRef.current === version) applyResults(data);
          })
          .catch(() => {
            if (searchVersionRef.current === version) applyFailure();
          })
          .finally(() => {
            if (searchVersionRef.current === version) setLoading(false);
          });
      }, 250);
    },
    [searchGroups, applyResults, applyFailure],
  );

  const openSearch = useCallback(() => {
    setMode("search");
    setQuery("");
    setLoading(true);
    // Version-guard against a race with an immediate keystroke (handleQueryChange
    // shares searchVersionRef; the latest interaction wins).
    const version = ++searchVersionRef.current;
    const symbol = contractSymbol(contractDisplayName);
    // Recommended = groups whose name/strategy matches the contract symbol. Take
    // the top 2 and float them to the top of the list, then all other open groups
    // (recency order) with the shown recs de-duped out. No visual label (1B).
    const recommended = symbol ? searchGroups(symbol) : Promise.resolve([]);
    void Promise.all([recommended, searchGroups("")])
      .then(([recs, all]) => {
        if (searchVersionRef.current !== version) return;
        const topRecs = recs.slice(0, 2);
        const recIds = new Set(topRecs.map((g) => g.id));
        const rest = all.filter((g) => !recIds.has(g.id));
        applyResults([...topRecs, ...rest]);
      })
      .catch(() => {
        if (searchVersionRef.current === version) applyFailure();
      })
      .finally(() => {
        if (searchVersionRef.current === version) setLoading(false);
      });
  }, [searchGroups, applyResults, applyFailure, contractDisplayName]);

  // Focus the input and position the popover once we've entered search mode.
  useEffect(() => {
    if (mode !== "search") return;
    inputRef.current?.focus({ preventScroll: true });
    updateDropdownPos();
  }, [mode, updateDropdownPos]);

  const closeSearch = useCallback(() => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    searchVersionRef.current++;
    setMode("display");
    setQuery("");
    setResults([]);
    setFailed(false);
    setDropdownPos(null);
  }, []);

  useEffect(() => {
    if (mode !== "search") return;
    const handleOutsideClick = (event: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        closeSearch();
      }
    };
    document.addEventListener("mousedown", handleOutsideClick);
    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);
    };
  }, [mode, closeSearch]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    itemRefs.current[highlightedIndex]?.scrollIntoView({ block: "nearest" });
  }, [highlightedIndex]);

  const handleSelect = (group: TradeGroupResult) => {
    closeSearch();
    void onSelect(group);
  };

  if (mode === "display") {
    // False positive: `openSearch` touches a ref, but it is handed to the
    // render prop to be wired onto a click handler, never invoked during
    // render. Both call sites (TradesTable, PositionsTable) only call it from
    // onClick.
    // eslint-disable-next-line react-hooks/refs
    return <>{renderTrigger(openSearch)}</>;
  }

  return (
    <div
      ref={containerRef}
      className="relative"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        value={query}
        onChange={(e) => handleQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            closeSearch();
          } else if (e.key === "ArrowDown") {
            if (results.length === 0) return;
            e.preventDefault();
            setHighlightedIndex((prev) => (prev + 1) % results.length);
          } else if (e.key === "ArrowUp") {
            if (results.length === 0) return;
            e.preventDefault();
            setHighlightedIndex(
              (prev) => (prev - 1 + results.length) % results.length,
            );
          } else if (e.key === "Enter") {
            const group = results[highlightedIndex];
            if (group && !disabled) {
              e.preventDefault();
              handleSelect(group);
            }
          }
        }}
        className="w-full min-w-[200px] rounded border border-blue-300 px-2 py-0.5 text-xs"
        placeholder="Search trade groups..."
        disabled={disabled}
      />
      {dropdownPos && (
        <div
          className="fixed z-50 max-h-[240px] w-max overflow-y-auto rounded border border-gray-200 bg-white shadow-lg"
          style={{
            left: dropdownPos.left,
            // Grow to fit the widest label (no wrapping); never narrower than the
            // trigger cell, never past the right edge of the viewport.
            minWidth: dropdownPos.width,
            maxWidth: window.innerWidth - dropdownPos.left - 8,
            ...(dropdownPos.flipUp
              ? { bottom: window.innerHeight - dropdownPos.top + 4 }
              : { top: dropdownPos.top }),
          }}
        >
          {loading && (
            <div className="px-3 py-2 text-xs text-gray-500">Searching...</div>
          )}
          {!loading && failed && (
            <div className="px-3 py-2 text-xs text-red-600">
              Search failed.
              <button
                onClick={openSearch}
                className="ml-1 underline hover:text-red-800"
              >
                Retry
              </button>
            </div>
          )}
          {!loading && !failed && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-gray-500">
              No trade groups found.
              <button
                onClick={() => {
                  const params = new URLSearchParams({
                    account_id: String(accountId),
                    prefill_group_name: `${contractDisplayName ?? "Trade"} Lifecycle Group`,
                  });
                  window.open(
                    `/strategies?${params.toString()}`,
                    "_blank",
                    "noopener,noreferrer",
                  );
                }}
                className="ml-1 text-blue-600 underline hover:text-blue-800"
              >
                Create one
              </button>
            </div>
          )}
          {!loading &&
            results.map((group, index) => (
              <button
                key={group.id}
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                onMouseEnter={() => setHighlightedIndex(index)}
                onClick={() => handleSelect(group)}
                disabled={disabled}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs disabled:opacity-50 ${
                  index === highlightedIndex ? "bg-blue-50" : "hover:bg-blue-50"
                }`}
              >
                <span className="whitespace-nowrap font-medium text-gray-800">
                  {tradeGroupLabel(group)}
                </span>
                <span className="ml-auto pl-2 text-gray-400">#{group.id}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
