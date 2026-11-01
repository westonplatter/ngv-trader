// The futures term structure and option chain catalog for the selected
// instrument. Both are stored with the instrument they were loaded for and
// derived against the current one, so switching instruments shows the
// loading state and empty lists until the new data lands, without clearing
// anything by hand.

import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type { ChainEntry, FuturesContract } from "../../types/pricing";

export interface InstrumentData {
  futuresContracts: FuturesContract[];
  availableOptions: ChainEntry[];
  futuresLoading: boolean;
  optionsLoading: boolean;
}

interface Loaded<T> {
  instrument: string;
  rows: T[];
}

const NO_FUTURES: FuturesContract[] = [];
const NO_OPTIONS: ChainEntry[] = [];

export function useInstrumentData(
  instrument: string,
  callbacks: {
    // The term structure arrived; the page seeds the spot inputs from it.
    onFuturesLoaded: (contracts: FuturesContract[]) => void;
    onError: (message: string) => void;
  },
): InstrumentData {
  const [futures, setFutures] = useState<Loaded<FuturesContract> | null>(null);
  const [options, setOptions] = useState<Loaded<ChainEntry> | null>(null);
  // Latest callbacks, read inside the async handlers below.
  const callbacksRef = useRef(callbacks);
  useEffect(() => {
    callbacksRef.current = callbacks;
  }, [callbacks]);

  useEffect(() => {
    let active = true;
    api
      .get<FuturesContract[]>(`/futures/${instrument}/term-structure?front_n=12`)
      .then((data) => {
        if (!active) return;
        setFutures({ instrument, rows: data });
        callbacksRef.current.onFuturesLoaded(data);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setFutures({ instrument, rows: [] });
        callbacksRef.current.onError(errorMessage(err, "Load failed"));
      });
    return () => {
      active = false;
    };
  }, [instrument]);

  useEffect(() => {
    let active = true;
    api
      .get<ChainEntry[]>(`/futures/${instrument}/chain`)
      .then((data) => {
        if (active) setOptions({ instrument, rows: data });
      })
      .catch((err: unknown) => {
        if (!active) return;
        setOptions({ instrument, rows: [] });
        callbacksRef.current.onError(errorMessage(err, "Load failed"));
      });
    return () => {
      active = false;
    };
  }, [instrument]);

  const futuresReady = futures?.instrument === instrument;
  const optionsReady = options?.instrument === instrument;
  return {
    futuresContracts: futuresReady ? futures.rows : NO_FUTURES,
    availableOptions: optionsReady ? options.rows : NO_OPTIONS,
    futuresLoading: !futuresReady,
    optionsLoading: !optionsReady,
  };
}
