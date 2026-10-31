// The selected trade group's detail row and its executions payload, as one
// value keyed by group id.
//
// The page used to hold these as eleven separate useState calls that were set
// together on load and cleared together when the selection emptied, which is
// what forced the set-state-in-effect suppression. Here the loaded data is
// stored with the id it belongs to and the result is *derived*: when the
// selection changes, the previous group's data simply stops matching and the
// caller sees the empty state until the new load lands. Nothing is cleared.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type {
  GroupExecutionsResponse,
  TradeGroupDetail,
} from "../../types/tradeGroups";

export interface TradeGroupDetailState {
  // GET /trade-groups/{id}; null until loaded or when no group is selected.
  detail: TradeGroupDetail | null;
  // GET /trade-groups/{id}/executions: executions, open positions, P&L totals,
  // the per-account split, and the live-mark timestamp. Null until loaded.
  executions: GroupExecutionsResponse | null;
  // Message from the most recent failed load for this group, cleared by the
  // next successful load of the same payload.
  error: string | null;
  // Re-fetch one payload for the currently selected group (after an edit or a
  // sync job). No-ops when nothing is selected.
  reloadDetail: () => Promise<void>;
  reloadExecutions: () => Promise<void>;
}

interface Loaded {
  groupId: number;
  detail: TradeGroupDetail | null;
  executions: GroupExecutionsResponse | null;
  error: string | null;
}

const EMPTY: Pick<Loaded, "detail" | "executions" | "error"> = {
  detail: null,
  executions: null,
  error: null,
};

export function useTradeGroupDetail(
  groupId: number | null,
): TradeGroupDetailState {
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  // The id currently selected, for the async callbacks below. A response for
  // a group the operator has already clicked away from is dropped rather than
  // merged, so a slow fetch can never overwrite the new selection; and a
  // reload always targets the current group, even when it was queued (by a
  // job watcher) while another group was selected.
  const selectedRef = useRef(groupId);
  useEffect(() => {
    selectedRef.current = groupId;
  }, [groupId]);

  const merge = useCallback((id: number, patch: Partial<Loaded>) => {
    if (selectedRef.current !== id) return;
    setLoaded((current) =>
      current && current.groupId === id
        ? { ...current, ...patch }
        : { groupId: id, ...EMPTY, ...patch },
    );
  }, []);

  // Promise chains rather than async/await so the state writes are visibly in
  // callbacks, not in the effect body that starts the fetch.
  const fetchDetail = useCallback(
    (id: number) =>
      api
        .get<TradeGroupDetail>(`/trade-groups/${id}`, {
          fallback: "Unable to load group detail",
        })
        .then((detail) => merge(id, { detail, error: null }))
        .catch((err: unknown) =>
          merge(id, {
            error: errorMessage(err, "Failed to load group detail."),
          }),
        ),
    [merge],
  );

  const fetchExecutions = useCallback(
    (id: number) =>
      api
        .get<GroupExecutionsResponse>(`/trade-groups/${id}/executions`, {
          fallback: "Unable to load group executions",
        })
        .then((executions) => merge(id, { executions, error: null }))
        .catch((err: unknown) =>
          merge(id, {
            error: errorMessage(err, "Failed to load trade group executions."),
          }),
        ),
    [merge],
  );

  useEffect(() => {
    if (groupId == null) return;
    void fetchDetail(groupId);
    void fetchExecutions(groupId);
  }, [groupId, fetchDetail, fetchExecutions]);

  const reloadDetail = useCallback(() => {
    const id = selectedRef.current;
    return id == null ? Promise.resolve() : fetchDetail(id);
  }, [fetchDetail]);

  const reloadExecutions = useCallback(() => {
    const id = selectedRef.current;
    return id == null ? Promise.resolve() : fetchExecutions(id);
  }, [fetchExecutions]);

  const current = loaded && loaded.groupId === groupId ? loaded : EMPTY;
  return {
    detail: current.detail,
    executions: current.executions,
    error: current.error,
    reloadDetail,
    reloadExecutions,
  };
}
