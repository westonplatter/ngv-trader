// The trade groups of the selected strategy and their writes. The loaded list
// is stored with the strategy it belongs to and derived against the current
// one, so switching strategies shows an empty list until the new load lands
// instead of clearing state in an effect (and never flashes the previous
// strategy's groups).

import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type { TradeGroup } from "../../types/tradeGroups";

export type GroupPatch = Record<string, string | number | null>;

export interface TradeGroupsData {
  // Null until the current strategy's groups have loaded (or when no strategy
  // is selected).
  groups: TradeGroup[] | null;
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  create: (body: {
    name: string;
    notes: string | null;
    strategy_id: number;
  }) => Promise<TradeGroup>;
  patch: (id: number, body: GroupPatch) => Promise<void>;
  remove: (id: number) => Promise<void>;
}

interface Loaded {
  strategyName: string;
  groups: TradeGroup[];
}

export function useTradeGroups(
  strategyName: string | null,
  // False while the strategies are still resolving; see useStrategies.
  enabled: boolean,
): TradeGroupsData {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback((name: string) => {
    const params = new URLSearchParams({ limit: "200", strategy: name });
    return api
      .get<TradeGroup[]>(`/trade-groups?${params.toString()}`, {
        fallback: "Unable to load trade groups",
      })
      .then((groups) => setLoaded({ strategyName: name, groups }));
  }, []);

  useEffect(() => {
    if (!enabled || !strategyName) return;
    let active = true;
    load(strategyName).catch((err: unknown) => {
      if (active) setError(errorMessage(err, "Failed to load trade groups."));
    });
    return () => {
      active = false;
    };
  }, [enabled, strategyName, load]);

  const reload = useCallback(
    () => (strategyName ? load(strategyName) : Promise.resolve()),
    [strategyName, load],
  );

  const create = useCallback(
    async (body: { name: string; notes: string | null; strategy_id: number }) => {
      const created = await api.post<TradeGroup>(
        "/trade-groups",
        { ...body, created_by: "ui-trader" },
        { fallback: "Unable to create trade group" },
      );
      await reload();
      return created;
    },
    [reload],
  );

  const patch = useCallback(
    (id: number, body: GroupPatch) =>
      api.patch<void>(`/trade-groups/${id}`, body, {
        fallback: "Unable to update trade group",
      }),
    [],
  );

  const remove = useCallback(
    async (id: number) => {
      await api.delete<void>(
        `/trade-groups/${id}?source=manual&created_by=ui-trader&reason=deleted+from+strategies+page`,
        undefined,
        { fallback: "Unable to delete trade group" },
      );
      await reload();
    },
    [reload],
  );

  const groups =
    strategyName && loaded && loaded.strategyName === strategyName
      ? loaded.groups
      : null;
  const loading = enabled && strategyName != null && groups === null;

  return { groups, loading, error, reload, create, patch, remove };
}
