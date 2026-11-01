// The legs table state and the quote fetch: queue a snapshot (or qualify)
// job for a contract and fold the result into the leg when the watcher
// reports it finished.

import { useCallback, useState } from "react";
import { useJobWatcher } from "../../hooks/useJobWatcher";
import { api, errorMessage } from "../../lib/api";
import {
  applyPriceJobResult,
  createEmptyLeg,
  priceJobPayload,
  type LegRow,
} from "../../lib/pricing/legs";
import type { ChainEntry } from "../../types/pricing";

const PRICE_FETCH_TIMEOUT_MS = 30 * 60 * 1000;

export interface Legs {
  legs: LegRow[];
  setLegs: (legs: LegRow[]) => void;
  updateLeg: (id: string, updates: Partial<LegRow>) => void;
  removeLeg: (id: string) => void;
  addLeg: () => void;
  fetchPriceForContract: (legId: string, entry: ChainEntry) => Promise<void>;
}

export function useLegs(onError: (message: string) => void): Legs {
  const [legs, setLegsState] = useState<LegRow[]>([createEmptyLeg()]);
  const { watch } = useJobWatcher();

  const setLegs = useCallback((next: LegRow[]) => setLegsState(next), []);
  const updateLeg = useCallback((id: string, updates: Partial<LegRow>) => {
    setLegsState((prev) =>
      prev.map((leg) => (leg.id === id ? { ...leg, ...updates } : leg)),
    );
  }, []);
  const removeLeg = useCallback((id: string) => {
    setLegsState((prev) => prev.filter((leg) => leg.id !== id));
  }, []);
  const addLeg = useCallback(() => {
    setLegsState((prev) => [...prev, createEmptyLeg()]);
  }, []);

  const fetchPriceForContract = useCallback(
    async (legId: string, entry: ChainEntry) => {
      setLegsState((prev) =>
        prev.map((l) =>
          l.id === legId ? { ...l, fetchStatus: "working", fetchJobId: null } : l,
        ),
      );
      try {
        const job = await api.post<{ id: number }>(
          "/jobs",
          priceJobPayload(entry),
        );
        setLegsState((prev) =>
          prev.map((l) => (l.id === legId ? { ...l, fetchJobId: job.id } : l)),
        );
        // Price fetches used to wait with no deadline; a long queue must not
        // strand the leg at "fetching", so allow well past the 5-minute default.
        watch(
          job.id,
          (done) =>
            setLegsState((prev) => applyPriceJobResult(prev, legId, done)),
          { timeoutMs: PRICE_FETCH_TIMEOUT_MS },
        );
      } catch (err) {
        setLegsState((prev) =>
          prev.map((l) => (l.id === legId ? { ...l, fetchStatus: "error" } : l)),
        );
        onError(`Failed to queue price fetch: ${errorMessage(err)}`);
      }
    },
    [watch, onError],
  );

  return { legs, setLegs, updateLeg, removeLeg, addLeg, fetchPriceForContract };
}
