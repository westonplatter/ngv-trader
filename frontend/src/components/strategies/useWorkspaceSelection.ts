// Which strategy and trade group the workspace is looking at. Both ids start
// from the URL (?strategy_id=&trade_group_id=) and are written back as they
// change, so the page is shareable and bookmarkable.

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { parseIdParam } from "../../lib/strategies/groups";

export interface DeepLink {
  strategyId: number | null;
  groupId: number | null;
}

export interface WorkspaceSelection {
  // The operator's choices. The page resolves them against the loaded lists
  // (a missing id falls back to the first entry) before using them.
  strategyId: number | null;
  groupId: number | null;
  setStrategyId: (id: number | null) => void;
  setGroupId: (id: number | null) => void;
  // The ids the page was opened with, captured once, for deep-link resolution.
  deepLink: DeepLink;
}

export function useWorkspaceSelection(): WorkspaceSelection {
  const [searchParams] = useSearchParams();
  const [deepLink] = useState<DeepLink>(() => ({
    strategyId: parseIdParam(searchParams.get("strategy_id")),
    groupId: parseIdParam(searchParams.get("trade_group_id")),
  }));
  const [strategyId, setStrategyId] = useState<number | null>(
    deepLink.strategyId,
  );
  const [groupId, setGroupId] = useState<number | null>(deepLink.groupId);
  return { strategyId, groupId, setStrategyId, setGroupId, deepLink };
}

// Keep the URL query params in sync with the resolved selection. Use replace
// so clicking around doesn't pile up browser history entries.
export function useSelectionUrlSync(
  strategyId: number | null,
  groupId: number | null,
): void {
  const [, setSearchParams] = useSearchParams();
  useEffect(() => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (strategyId != null) next.set("strategy_id", String(strategyId));
        else next.delete("strategy_id");
        if (groupId != null) next.set("trade_group_id", String(groupId));
        else next.delete("trade_group_id");
        return next;
      },
      { replace: true },
    );
  }, [strategyId, groupId, setSearchParams]);
}
