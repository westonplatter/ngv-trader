// Run a write against the API from a click: clears the last error, awaits the
// action, calls `onSuccess`, and keeps the failure message for display. While
// one action is in flight `pending` is true, so a button can be disabled and a
// double-click never sends the request twice.

import { useRef, useState } from "react";
import { errorMessage } from "../lib/api";

export function useAsyncAction(onSuccess?: () => void) {
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const inFlight = useRef(false);

  const run = async (action: () => Promise<unknown>) => {
    if (inFlight.current) return;
    inFlight.current = true;
    setPending(true);
    setError(null);
    try {
      await action();
      onSuccess?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      inFlight.current = false;
      setPending(false);
    }
  };

  return { run, error, pending, setError };
}
