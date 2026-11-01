// The strategy list and its writes, plus the one-time deep-link resolution:
// a page opened with only ?trade_group_id=N (a Trade Group link from the
// Positions page) must land on that group's parent strategy instead of
// falling back to the first strategy's first group.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { sortStrategies } from "../../lib/strategies/groups";
import type { Strategy } from "../../types/strategies";
import type { TradeGroupDetail } from "../../types/tradeGroups";
import type { DeepLink } from "./useWorkspaceSelection";

// Resolve which strategy owns a trade group. Returns the strategy name, or
// null if it can't be determined.
async function fetchGroupStrategyValue(
  groupId: number,
): Promise<string | null> {
  try {
    const detail = await api.get<TradeGroupDetail>(`/trade-groups/${groupId}`);
    return detail.primary_strategy_value;
  } catch {
    return null;
  }
}

export interface StrategiesData {
  strategies: Strategy[];
  // True until the first load and the deep-link resolution have settled. The
  // group list waits for this so a deep-linked group is not cleared while the
  // strategies are still loading.
  loading: boolean;
  error: string | null;
  reload: () => Promise<Strategy[]>;
  create: (name: string) => Promise<Strategy>;
  setArchived: (strategy: Strategy, archived: boolean) => Promise<void>;
}

export function useStrategies(options: {
  showArchived: boolean;
  deepLink: DeepLink;
  // Called once when the deep link names a group whose strategy is not the
  // one in the URL: select that strategy and the group.
  onDeepLink: (strategyId: number, groupId: number) => void;
}): StrategiesData {
  const { showArchived, deepLink, onDeepLink } = options;
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const resolvedRef = useRef(false);
  const onDeepLinkRef = useRef(onDeepLink);
  useEffect(() => {
    onDeepLinkRef.current = onDeepLink;
  }, [onDeepLink]);

  const reload = useCallback(() => {
    const params = new URLSearchParams({ limit: "200" });
    if (showArchived) params.set("include_archived", "true");
    return api
      .get<Strategy[]>(`/strategies?${params.toString()}`, {
        fallback: "Unable to load strategies",
      })
      .then((raw) => {
        const data = sortStrategies(raw);
        setStrategies(data);
        return data;
      });
  }, [showArchived]);

  useEffect(() => {
    let active = true;
    reload()
      .then(async (data) => {
        if (!active || resolvedRef.current) return;
        resolvedRef.current = true;
        const { groupId, strategyId } = deepLink;
        const strategyParamValid =
          strategyId != null &&
          data.some((strategy) => strategy.id === strategyId);
        if (groupId != null && !strategyParamValid) {
          const ownerValue = await fetchGroupStrategyValue(groupId);
          if (!active) return;
          const owner = ownerValue
            ? data.find((strategy) => strategy.name === ownerValue)
            : undefined;
          if (owner) onDeepLinkRef.current(owner.id, groupId);
        }
      })
      .catch((err: unknown) => {
        if (active)
          setError(errorMessage(err, "Failed to load strategies workspace."));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload, deepLink]);

  const create = useCallback(
    async (name: string) => {
      const created = await api.post<Strategy>(
        "/strategies",
        { name, created_by: "ui-trader" },
        { fallback: "Unable to create strategy" },
      );
      await reload();
      return created;
    },
    [reload],
  );

  const setArchived = useCallback(
    async (strategy: Strategy, archived: boolean) => {
      const action = archived ? "archive" : "unarchive";
      await api.post(`/strategies/${strategy.id}/${action}`, undefined, {
        fallback: `Unable to ${action} strategy`,
      });
      await reload();
    },
    [reload],
  );

  return { strategies, loading, error, reload, create, setArchived };
}
