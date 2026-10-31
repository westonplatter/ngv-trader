// The positions snapshot: REST load on mount, re-fetched whenever the
// `positions` SSE topic fires (the backend sends a coarse "changed" event, not
// row deltas), plus the trade-group assign and unassign writes that reload it.

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { useSSE } from "../../lib/events";
import type { Position } from "../../types/positions";

export interface PositionsData {
  positions: Position[];
  // True until the first load settles.
  loading: boolean;
  // Message from a failed load; the page shows it in place of the table.
  error: string | null;
  // Message from the last failed assign or unassign, cleared on the next try.
  assignError: string | null;
  reload: () => void;
  assignToTradeGroup: (pos: Position, groupId: number) => Promise<void>;
  unassignFromTradeGroup: (pos: Position, groupId: number) => Promise<void>;
}

export function usePositions(): PositionsData {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [assignError, setAssignError] = useState<string | null>(null);

  const reload = useCallback(() => {
    api
      .get<Position[]>("/positions")
      .then(setPositions)
      .catch((err: unknown) => setError(errorMessage(err, "Load failed")))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useSSE<Record<string, unknown>>("positions", () => {
    reload();
  });

  const membership = useCallback(
    async (
      action: "assign" | "unassign",
      pos: Position,
      groupId: number,
      failed: string,
    ) => {
      setAssignError(null);
      try {
        await api.post(`/trade-groups/${groupId}/positions:${action}`, {
          positions: [{ account_id: pos.account_id, con_id: pos.con_id }],
          source: "manual",
          created_by: "positions-ui",
        });
        reload();
      } catch (err) {
        setAssignError(err instanceof Error ? err.message : failed);
      }
    },
    [reload],
  );

  const assignToTradeGroup = useCallback(
    (pos: Position, groupId: number) =>
      membership("assign", pos, groupId, "Assign failed"),
    [membership],
  );
  const unassignFromTradeGroup = useCallback(
    (pos: Position, groupId: number) =>
      membership("unassign", pos, groupId, "Unassign failed"),
    [membership],
  );

  return {
    positions,
    loading,
    error,
    assignError,
    reload,
    assignToTradeGroup,
    unassignFromTradeGroup,
  };
}
