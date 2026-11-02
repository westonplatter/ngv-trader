// The tag search: the all / any / exclude lists and the active tab live in the
// URL (so a search is a link), "include closed positions" is local, and the
// matching items are fetched whenever the filters change.

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  applyParamUpdates,
  parseTab,
  splitList,
  type Tab,
} from "../../lib/tagBrowser";
import { tagsApi } from "../../lib/tags";
import type { TaggedItem } from "../../types/tags";

export interface TagSearch {
  all: string[];
  any: string[];
  none: string[];
  tab: Tab;
  includeEnded: boolean;
  setIncludeEnded: (include: boolean) => void;
  /** True once there is a tag to search for; otherwise `items` is empty. */
  hasFilter: boolean;
  items: TaggedItem[];
  /** Change several URL keys in one update. */
  setParams: (updates: Record<string, string[] | string>) => void;
  setParam: (key: string, values: string[] | string) => void;
  reload: () => void;
}

export function useTagSearch(onError: (message: string) => void): TagSearch {
  const [searchParams, setSearchParams] = useSearchParams();
  const [includeEnded, setIncludeEnded] = useState(false);
  const [fetchedItems, setItems] = useState<TaggedItem[]>([]);
  // Bumped to refetch with the same filters.
  const [version, setVersion] = useState(0);

  // Memoized on the raw URL text so the lists are stable between renders and
  // can be effect dependencies.
  const allText = searchParams.get("all") ?? "";
  const anyText = searchParams.get("any") ?? "";
  const noneText = searchParams.get("none") ?? "";
  const all = useMemo(() => splitList(allText), [allText]);
  const any = useMemo(() => splitList(anyText), [anyText]);
  const none = useMemo(() => splitList(noneText), [noneText]);
  const tab = parseTab(searchParams.get("tab"));
  const hasFilter = all.length > 0 || any.length > 0;

  // One update for several keys: react-router does not chain functional
  // setSearchParams updates made in the same tick, so the last would win.
  const setParams = useCallback(
    (updates: Record<string, string[] | string>) => {
      setSearchParams((prev) => applyParamUpdates(prev, updates), {
        replace: true,
      });
    },
    [setSearchParams],
  );
  const setParam = useCallback(
    (key: string, values: string[] | string) => setParams({ [key]: values }),
    [setParams],
  );

  useEffect(() => {
    // With no tag chosen there is nothing to search; the page shows a prompt.
    if (!hasFilter) return;
    let cancelled = false;
    tagsApi
      .search({ all, any, none, includeEnded })
      .then((result) => {
        if (!cancelled) setItems(result.items);
      })
      .catch((err: Error) => {
        if (!cancelled) onError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [hasFilter, all, any, none, includeEnded, version, onError]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const items = useMemo(
    () => (hasFilter ? fetchedItems : []),
    [hasFilter, fetchedItems],
  );

  return {
    all,
    any,
    none,
    tab,
    includeEnded,
    setIncludeEnded,
    hasFilter,
    items,
    setParams,
    setParam,
    reload,
  };
}
