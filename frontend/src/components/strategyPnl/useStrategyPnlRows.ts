// The data behind the Strategy P&L table: the filters (status, account, and a
// debounced instrument pattern), the trade-group rows they select, and the
// account list for the filter. Rows are stored with the request that produced
// them, so "loading" is derived rather than set by hand.

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../lib/api";
import { buildTradeGroupsQuery } from "../../lib/strategyPnl";
import type { Account } from "../../types/accounts";
import type { TradeGroupPnlRow } from "../../types/tradeGroups";

interface Loaded {
  query: string;
  version: number;
  rows: TradeGroupPnlRow[];
  error: string | null;
}

export interface StrategyPnlRows {
  status: string;
  setStatus: (status: string) => void;
  accountId: string;
  setAccountId: (id: string) => void;
  /** What the input shows; `instrument` follows it after a short pause. */
  instrumentInput: string;
  setInstrumentInput: (text: string) => void;
  filtersActive: boolean;
  rows: TradeGroupPnlRow[];
  accounts: Account[];
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useStrategyPnlRows(): StrategyPnlRows {
  const [status, setStatus] = useState("open");
  const [accountId, setAccountId] = useState("all");
  const [instrumentInput, setInstrumentInput] = useState("");
  const [instrument, setInstrument] = useState("");
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // Bumped to refetch with the same filters.
  const [version, setVersion] = useState(0);

  // Debounce the pattern input: every keystroke of "CL.*" is otherwise a request,
  // and the intermediate "CL[" would 400.
  useEffect(() => {
    const handle = window.setTimeout(() => setInstrument(instrumentInput), 350);
    return () => window.clearTimeout(handle);
  }, [instrumentInput]);

  const query = useMemo(
    () => buildTradeGroupsQuery({ status, accountId, instrument }),
    [status, accountId, instrument],
  );

  useEffect(() => {
    let cancelled = false;
    // A malformed instrument pattern comes back as a 400 with a readable
    // message; the client surfaces that rather than an opaque status code.
    api
      .get<TradeGroupPnlRow[]>(`/trade-groups?${query}`)
      .then((rows) => {
        if (!cancelled) setLoaded({ query, version, rows, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setLoaded({
          query,
          version,
          rows: [],
          error:
            err instanceof Error ? err.message : "Failed to load trade groups.",
        });
      });
    // A newer request supersedes this one; its answer is the one to keep.
    return () => {
      cancelled = true;
    };
  }, [query, version]);

  useEffect(() => {
    api
      .get<Account[]>("/accounts")
      .then(setAccounts)
      .catch(() => {
        /* the account filter degrades to "All accounts" */
      });
  }, []);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return {
    status,
    setStatus,
    accountId,
    setAccountId,
    instrumentInput,
    setInstrumentInput,
    filtersActive:
      status !== "open" || accountId !== "all" || instrument.trim() !== "",
    // Until the first answer, and while a newer request is out, show the last
    // rows with a "Loading…" note.
    rows: loaded?.rows ?? [],
    accounts,
    loading:
      loaded == null || loaded.query !== query || loaded.version !== version,
    error: loaded?.error ?? null,
    reload,
  };
}
