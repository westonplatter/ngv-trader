// The picker's search state machine: closed ("display") or open ("search"), the
// text box, the debounced text search, the recommended-first opening list, and
// the keyboard highlight.
//
// Searches are driven by a `request` in state and run in an effect, so a newer
// request (or closing the picker) cancels the older one in the effect cleanup;
// no version counter in a ref is needed. The answer is stored with the request's
// `seq`, so "Searching…" is derived: a request is out until its answer lands.

import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import {
  contractSymbol,
  mergeRecommended,
  recommendedSearchParams,
  stepHighlight,
  textSearchParams,
} from "../../lib/tradeGroupSearch";
import type { TradeGroupResult } from "../../types/tradeGroups";

// `fetch` has no default timeout: a request the server accepts but never answers
// — an API restart dropping an in-flight connection, say — leaves its promise
// pending forever, so the picker would sit on "Searching..." with no way back.
// Bounding it turns that into an ordinary rejection the caller can recover from.
const SEARCH_TIMEOUT_MS = 8000;
const TYPING_DEBOUNCE_MS = 250;

function fetchGroups(params: URLSearchParams): Promise<TradeGroupResult[]> {
  return api.get<TradeGroupResult[]>(`/trade-groups?${params.toString()}`, {
    signal: AbortSignal.timeout(SEARCH_TIMEOUT_MS),
    fallback: "Unable to search trade groups",
  });
}

interface Request {
  seq: number;
  text: string;
  /** Set on open: also fetch the groups already holding this underlying. */
  symbol: string | null;
}

interface Answer {
  seq: number;
  results: TradeGroupResult[];
  // A failed search is not an empty one: without this, a dropped request reads
  // as "No trade groups found" and invites creating a duplicate group.
  failed: boolean;
  highlighted: number;
}

export interface TradeGroupSearch {
  mode: "display" | "search";
  query: string;
  results: TradeGroupResult[];
  loading: boolean;
  failed: boolean;
  highlightedIndex: number;
  /** Open the picker and load the recommended-first list. Also the Retry. */
  open: () => void;
  close: () => void;
  changeQuery: (text: string) => void;
  moveHighlight: (delta: 1 | -1) => void;
  setHighlightedIndex: (index: number) => void;
}

export function useTradeGroupSearch(
  contractDisplayName: string | null,
): TradeGroupSearch {
  const [mode, setMode] = useState<"display" | "search">("display");
  const [query, setQuery] = useState("");
  // True once the person has typed, so opening does not schedule a second
  // search for the empty box.
  const [typed, setTyped] = useState(false);
  const [request, setRequest] = useState<Request | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);

  const open = useCallback(() => {
    setMode("search");
    setQuery("");
    setTyped(false);
    setRequest((prev) => ({
      seq: (prev?.seq ?? 0) + 1,
      text: "",
      symbol: contractSymbol(contractDisplayName),
    }));
  }, [contractDisplayName]);

  const close = useCallback(() => {
    setMode("display");
    setQuery("");
    setTyped(false);
    setRequest(null);
    setAnswer(null);
  }, []);

  const changeQuery = useCallback((text: string) => {
    setQuery(text);
    setTyped(true);
  }, []);

  // Typing: wait for a pause, then search the text. Each keystroke restarts the
  // wait; closing clears it.
  useEffect(() => {
    if (mode !== "search" || !typed) return;
    const handle = window.setTimeout(() => {
      setRequest((prev) => ({
        seq: (prev?.seq ?? 0) + 1,
        text: query,
        symbol: null,
      }));
    }, TYPING_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [mode, typed, query]);

  useEffect(() => {
    if (!request) return;
    let cancelled = false;
    const { seq, text, symbol } = request;
    // Recommended = groups already carrying this underlying: the top two float
    // to the top, then all other open groups with those de-duped out.
    const load = symbol
      ? Promise.all([
          fetchGroups(recommendedSearchParams(symbol)),
          fetchGroups(textSearchParams(text)),
        ]).then(([recs, all]) => mergeRecommended(recs, all))
      : fetchGroups(textSearchParams(text));
    load
      .then((results) => {
        if (!cancelled)
          setAnswer({ seq, results, failed: false, highlighted: 0 });
      })
      .catch(() => {
        if (!cancelled)
          setAnswer({ seq, results: [], failed: true, highlighted: 0 });
      });
    return () => {
      cancelled = true;
    };
  }, [request]);

  const results = answer?.results ?? [];
  const highlightedIndex = answer?.highlighted ?? 0;

  const setHighlightedIndex = useCallback((index: number) => {
    setAnswer((prev) => (prev ? { ...prev, highlighted: index } : prev));
  }, []);

  const moveHighlight = useCallback((delta: 1 | -1) => {
    setAnswer((prev) =>
      prev
        ? {
            ...prev,
            highlighted: stepHighlight(
              prev.highlighted,
              delta,
              prev.results.length,
            ),
          }
        : prev,
    );
  }, []);

  return {
    mode,
    query,
    results,
    loading: request != null && answer?.seq !== request.seq,
    failed: answer?.failed ?? false,
    highlightedIndex,
    open,
    close,
    changeQuery,
    moveHighlight,
    setHighlightedIndex,
  };
}
