// A list that is loaded over REST and then kept current from one SSE topic.
//
// Every live table (jobs, orders, worker lights) does the same three things:
// fetch the snapshot on mount, upsert each pushed row by key, and re-fetch the
// snapshot after the stream reconnects. This hook owns that so each table only
// says which topic it follows and how to load its rows.

import { useCallback, useEffect, useRef, useState } from "react";
import { useSSE, type ConnectionStatus } from "../lib/events";
import { errorMessage } from "../lib/api";

// Run `reload` once each time the stream goes from disconnected to connected,
// so rows that changed during the gap are picked up.
export function useRefetchOnReconnect(
  status: ConnectionStatus,
  reload: () => void,
): void {
  const prevStatusRef = useRef<ConnectionStatus | null>(null);
  useEffect(() => {
    if (prevStatusRef.current === "disconnected" && status === "connected") {
      reload();
    }
    prevStatusRef.current = status;
  }, [status, reload]);
}

export interface SseListOptions<T> {
  topic: string;
  // Fetch the REST snapshot. Called on mount, on `reload()`, and on reconnect.
  load: () => Promise<T[]>;
  // Identity used to upsert a pushed row over the one already in the list.
  key: (item: T) => string | number;
  // Keep at most this many rows (newest first) after an upsert.
  cap?: number;
  // Ignore pushed rows that do not belong in this list.
  accept?: (payload: T, eventType: string) => boolean;
  // Event types that remove the row instead of upserting it.
  removeOn?: readonly string[];
  // Side effects to run for a pushed row before it is merged.
  onEvent?: (payload: T, eventType: string) => void;
}

export interface SseList<T> {
  items: T[];
  setItems: React.Dispatch<React.SetStateAction<T[]>>;
  // Message from the last failed load, cleared by the next success.
  error: string | null;
  // True until the first load settles.
  loading: boolean;
  status: ConnectionStatus;
  reload: () => void;
}

export function upsertByKey<T>(
  rows: T[],
  row: T,
  key: (item: T) => string | number,
  cap?: number,
): T[] {
  const id = key(row);
  const idx = rows.findIndex((existing) => key(existing) === id);
  let next: T[];
  if (idx >= 0) {
    next = [...rows];
    next[idx] = row;
  } else {
    next = [row, ...rows];
  }
  return cap === undefined ? next : next.slice(0, cap);
}

export function useSseList<T>(options: SseListOptions<T>): SseList<T> {
  const { topic, load, key, cap, accept, removeOn, onEvent } = options;
  const [items, setItems] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(() => {
    load()
      .then((rows) => {
        setItems(cap === undefined ? rows : rows.slice(0, cap));
        setError(null);
      })
      .catch((err: unknown) => setError(errorMessage(err, "Load failed")))
      .finally(() => setLoading(false));
  }, [load, cap]);

  useEffect(() => {
    reload();
  }, [reload]);

  const handleEvent = useCallback(
    (payload: T, eventType: string) => {
      if (accept && !accept(payload, eventType)) return;
      onEvent?.(payload, eventType);
      if (removeOn?.includes(eventType)) {
        const id = key(payload);
        setItems((prev) => prev.filter((row) => key(row) !== id));
        return;
      }
      setItems((prev) => upsertByKey(prev, payload, key, cap));
    },
    [accept, onEvent, removeOn, key, cap],
  );

  const status = useSSE<T>(topic, handleEvent);
  useRefetchOnReconnect(status, reload);

  return { items, setItems, error, loading, status, reload };
}
