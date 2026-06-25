import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";
import {
  type TradeGroupResult,
  tradeGroupLabel,
} from "../lib/tradeGroups";

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
  const [highlightedIndex, setHighlightedIndex] = useState(0);
  const [dropdownPos, setDropdownPos] = useState<{
    top: number;
    left: number;
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
      flipUp,
    });
  }, []);

  const searchGroups = useCallback(async (searchQuery: string) => {
    const params = new URLSearchParams({ limit: "20", status: "open" });
    if (searchQuery.trim()) params.set("q", searchQuery.trim());
    const response = await fetch(
      `${API_BASE_URL}/trade-groups?${params.toString()}`,
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
            if (searchVersionRef.current === version) applyResults([]);
          })
          .finally(() => {
            if (searchVersionRef.current === version) setLoading(false);
          });
      }, 250);
    },
    [searchGroups, applyResults],
  );

  const openSearch = useCallback(() => {
    setMode("search");
    setQuery("");
    setLoading(true);
    void searchGroups("")
      .then((data) => applyResults(data))
      .catch(() => applyResults([]))
      .finally(() => setLoading(false));
  }, [searchGroups, applyResults]);

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
        className="w-full min-w-[200px] rounded border border-blue-300 px-2 py-1 text-xs"
        placeholder="Search trade groups..."
        disabled={disabled}
      />
      {dropdownPos && (
        <div
          className="fixed z-50 max-h-[240px] w-[320px] overflow-y-auto rounded border border-gray-200 bg-white shadow-lg"
          style={{
            left: dropdownPos.left,
            ...(dropdownPos.flipUp
              ? { bottom: window.innerHeight - dropdownPos.top + 4 }
              : { top: dropdownPos.top }),
          }}
        >
          {loading && (
            <div className="px-3 py-2 text-xs text-gray-500">Searching...</div>
          )}
          {!loading && results.length === 0 && (
            <div className="px-3 py-2 text-xs text-gray-500">
              No trade groups found.
              <button
                onClick={() => {
                  const params = new URLSearchParams({
                    account_id: String(accountId),
                    prefill_group_name: `${contractDisplayName ?? "Trade"} Lifecycle Group`,
                  });
                  window.open(
                    `/tagging?${params.toString()}`,
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
                <span className="font-medium text-gray-800">
                  {tradeGroupLabel(group)}
                </span>
                <span className="ml-auto text-gray-400">#{group.id}</span>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
