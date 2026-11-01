// The "Refresh Live (TWS)" button: queue an intraday overlay sync job, show its
// status line, and call `onFinished` once the worker reports the job done.

import { useState } from "react";
import { enqueueSyncJob, useJobWatcher } from "../../hooks/useJobWatcher";

export interface IntradayRefresh {
  syncing: boolean;
  message: string | null;
  kickOff: () => Promise<void>;
}

export function useIntradayRefresh(onFinished: () => void): IntradayRefresh {
  const { watch } = useJobWatcher();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const kickOff = async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const data = await enqueueSyncJob(
        "/positions/sync/intraday-tws",
        "Refresh live intraday overlay from the Strategy P&L table.",
      );
      setMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      watch(data.job_id, onFinished);
    } catch (err: unknown) {
      setMessage(err instanceof Error ? err.message : "Failed to queue sync.");
    } finally {
      setSyncing(false);
    }
  };

  return { syncing, message, kickOff };
}
