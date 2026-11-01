// The executions snapshot and the trade-group labels it is rendered with.
// Loaded over REST, re-fetched when the `trades` SSE topic fires, and
// re-fetched on demand after an assignment, a tag change, or a finished sync.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { useSSE } from "../../lib/events";
import { tradeGroupLabel } from "../../lib/tradeGroups";
import type { TradeExecutionRow } from "../../types/trades";
import type { TradeGroupResult } from "../../types/tradeGroups";

export interface TradeExecutionsQuery {
  // Server-side pre-filters; the rest of the filtering is client-side.
  serverSymbol: string | null;
  conId: number | null;
}

export interface TradeExecutionsData {
  executions: TradeExecutionRow[];
  // Clock the relative "last 24h/3d/..." filter measures against. Taken when
  // executions arrive and when the range changes, rather than during render —
  // reading the clock while rendering is impure and would let the window
  // drift on unrelated re-renders.
  filterNow: number;
  markNow: () => void;
  // True until the first load settles.
  loading: boolean;
  // Message from the last failed load, cleared by the next success.
  error: string | null;
  groupLabelById: Map<number, string>;
  // Re-fetch executions; a failure lands in `error`.
  refreshQuietly: () => void;
  // Re-fetch executions and group labels; failures are ignored (the stream
  // catches up). For "something changed" callbacks.
  reloadAll: () => void;
}

export function useTradeExecutions(
  query: TradeExecutionsQuery,
): TradeExecutionsData {
  const { serverSymbol, conId } = query;
  const [executions, setExecutions] = useState<TradeExecutionRow[]>([]);
  const [filterNow, setFilterNow] = useState(() => Date.now());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tradeGroups, setTradeGroups] = useState<TradeGroupResult[]>([]);

  const groupLabelById = useMemo(() => {
    const map = new Map<number, string>();
    for (const group of tradeGroups) {
      map.set(group.id, tradeGroupLabel(group));
    }
    return map;
  }, [tradeGroups]);

  // Label lookup only: a failure leaves ids unlabeled rather than surfacing a
  // page-level error.
  const loadTradeGroups = useCallback(
    () =>
      api
        .get<TradeGroupResult[]>("/trade-groups?limit=500")
        .then(setTradeGroups)
        .catch(() => {}),
    [],
  );

  const loadExecutions = useCallback(() => {
    const params = new URLSearchParams({ limit: "5000" });
    if (conId !== null) params.set("con_id", String(conId));
    else if (serverSymbol) params.set("symbol", serverSymbol);
    return api
      .get<TradeExecutionRow[]>(`/trade-executions?${params.toString()}`, {
        fallback: "Unable to load executions",
      })
      .then((data) => {
        setExecutions(data);
        setFilterNow(Date.now());
        setError(null);
      });
  }, [serverSymbol, conId]);

  useEffect(() => {
    let cancelled = false;
    void loadTradeGroups();
    loadExecutions()
      .catch((err: unknown) => {
        if (!cancelled)
          setError(errorMessage(err, "Unknown executions load error"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [loadExecutions, loadTradeGroups]);

  const reloadAll = useCallback(() => {
    void loadExecutions().catch(() => {});
    void loadTradeGroups();
  }, [loadExecutions, loadTradeGroups]);

  useSSE<Record<string, unknown>>("trades", reloadAll);

  const refreshQuietly = useCallback(() => {
    loadExecutions().catch((err: unknown) => setError(errorMessage(err)));
  }, [loadExecutions]);

  const markNow = useCallback(() => setFilterNow(Date.now()), []);

  return {
    executions,
    filterNow,
    markNow,
    loading,
    error,
    groupLabelById,
    refreshQuietly,
    reloadAll,
  };
}
