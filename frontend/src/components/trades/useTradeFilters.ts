// The Trades page filters live in the URL (?account=&range=&group=&cols=
// &symbol=&con_id=) so a refresh or a shared link restores the view. Defaults
// are omitted to keep URLs short. This is the only place on the page that
// touches useSearchParams.

import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  parseConId,
  parseGroupStatus,
  type GroupStatus,
  type TradeFilters,
} from "../../lib/trades/view";

export interface TradeFilterState {
  filters: TradeFilters;
  // The id/reference columns (Parent Exec ID, Order Ref, Exec ID, Con ID) are
  // hidden unless the Columns toggle is on, keeping the default view compact.
  showDetails: boolean;
  // Set when the page was opened from a Positions "Con ID" link: every
  // execution for that contract across all time and all accounts.
  conId: number | null;
  setAccount: (value: string) => void;
  setSymbol: (value: string) => void;
  setTimeRange: (value: string) => void;
  setGroupStatus: (value: GroupStatus) => void;
  setShowDetails: (value: boolean) => void;
  clearConId: () => void;
}

export function useTradeFilters(): TradeFilterState {
  const [searchParams, setSearchParams] = useSearchParams();

  const setParam = useCallback(
    (key: string, value: string, defaultValue: string) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value === defaultValue) next.delete(key);
          else next.set(key, value);
          return next;
        },
        { replace: true },
      );
    },
    [setSearchParams],
  );

  // Default to the last 30 days for performance (fewer rows rendered). The
  // con_id deep-link case wants every execution for a contract, so it opts out.
  const defaultTimeRange = searchParams.get("con_id") ? "all" : "30d";

  const filters = useMemo<TradeFilters>(
    () => ({
      account: searchParams.get("account") ?? "all",
      symbol: searchParams.get("symbol") ?? "",
      timeRange: searchParams.get("range") ?? defaultTimeRange,
      groupStatus: parseGroupStatus(searchParams.get("group")),
    }),
    [searchParams, defaultTimeRange],
  );
  const conId = useMemo(
    () => parseConId(searchParams.get("con_id")),
    [searchParams],
  );

  return {
    filters,
    showDetails: searchParams.get("cols") === "all",
    conId,
    setAccount: (value) => setParam("account", value, "all"),
    setSymbol: (value) => setParam("symbol", value, ""),
    setTimeRange: (value) => setParam("range", value, defaultTimeRange),
    setGroupStatus: (value) => setParam("group", value, "all"),
    setShowDetails: (value) =>
      setParam("cols", value ? "all" : "simple", "simple"),
    clearConId: () =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete("con_id");
          return next;
        },
        { replace: true },
      ),
  };
}
