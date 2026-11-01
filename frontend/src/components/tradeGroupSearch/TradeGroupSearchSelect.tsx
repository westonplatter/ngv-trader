import type React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  popoverPosition,
  type PopoverPosition,
} from "../../lib/tradeGroupSearch";
import { tradeGroupLabel } from "../../lib/tradeGroups";
import type { TradeGroupResult } from "../../types/tradeGroups";
import { useTradeGroupSearch } from "./useTradeGroupSearch";

/**
 * A searchable trade-group picker shared by the Positions and Trades tables.
 *
 * The caller supplies the trigger affordance via `renderTrigger` (e.g. a
 * "+ Assign" button or an assigned-group chip) and receives the chosen group
 * through `onSelect`. This component owns only the search interaction: opening
 * a popover, keyboard navigation, and click-away / Esc dismissal. The search
 * itself (debounce, recommendations, stale-answer handling) is in
 * `useTradeGroupSearch`. Assignment side effects stay with the caller.
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
  const search = useTradeGroupSearch(contractDisplayName);
  const { mode, close } = search;
  const [dropdownPos, setDropdownPos] = useState<PopoverPosition | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const updateDropdownPos = useCallback(() => {
    if (!inputRef.current) return;
    setDropdownPos(
      popoverPosition(
        inputRef.current.getBoundingClientRect(),
        window.innerHeight,
      ),
    );
  }, []);

  // Focus the input and position the popover once we've entered search mode.
  useEffect(() => {
    if (mode !== "search") return;
    inputRef.current?.focus({ preventScroll: true });
    updateDropdownPos();
  }, [mode, updateDropdownPos]);

  // Closing also drops the popover position, so the next open measures afresh.
  const closeSearch = useCallback(() => {
    close();
    setDropdownPos(null);
  }, [close]);

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

  // Keep the highlighted option scrolled into view.
  useEffect(() => {
    itemRefs.current[search.highlightedIndex]?.scrollIntoView({
      block: "nearest",
    });
  }, [search.highlightedIndex]);

  const handleSelect = (group: TradeGroupResult) => {
    closeSearch();
    void onSelect(group);
  };

  if (mode === "display") {
    return <>{renderTrigger(search.open)}</>;
  }

  return (
    <div
      ref={containerRef}
      className="relative"
      onClick={(e) => e.stopPropagation()}
    >
      <input
        ref={inputRef}
        value={search.query}
        onChange={(e) => search.changeQuery(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            closeSearch();
          } else if (e.key === "ArrowDown") {
            if (search.results.length === 0) return;
            e.preventDefault();
            search.moveHighlight(1);
          } else if (e.key === "ArrowUp") {
            if (search.results.length === 0) return;
            e.preventDefault();
            search.moveHighlight(-1);
          } else if (e.key === "Enter") {
            const group = search.results[search.highlightedIndex];
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
          {search.loading && (
            <div className="px-3 py-2 text-xs text-gray-500">Searching...</div>
          )}
          {!search.loading && search.failed && (
            <div className="px-3 py-2 text-xs text-red-600">
              Search failed.
              <button
                type="button"
                onClick={search.open}
                className="ml-1 underline hover:text-red-800"
              >
                Retry
              </button>
            </div>
          )}
          {!search.loading && !search.failed && search.results.length === 0 && (
            <div className="px-3 py-2 text-xs text-gray-500">
              No trade groups found.
              <button
                type="button"
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
          {!search.loading &&
            search.results.map((group, index) => (
              <button
                type="button"
                key={group.id}
                ref={(el) => {
                  itemRefs.current[index] = el;
                }}
                onMouseEnter={() => search.setHighlightedIndex(index)}
                onClick={() => handleSelect(group)}
                disabled={disabled}
                className={`flex w-full items-center gap-2 px-3 py-2 text-left text-xs disabled:opacity-50 ${
                  index === search.highlightedIndex
                    ? "bg-blue-50"
                    : "hover:bg-blue-50"
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
