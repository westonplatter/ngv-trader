// The "Refresh Live (TWS)" button in a group's detail: queue the intraday
// overlay sync and re-fetch the group's executions when it finishes.

import { useCallback, useState } from "react";
import { enqueueSyncJob, useJobWatcher } from "../../hooks/useJobWatcher";
import { errorMessage } from "../../lib/api";

export interface GroupLiveSync {
  syncing: boolean;
  message: string | null;
  kickOff: () => Promise<void>;
}

export function useGroupLiveSync(onDone: () => void): GroupLiveSync {
  const { watch } = useJobWatcher();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const kickOff = useCallback(async () => {
    setSyncing(true);
    setMessage(null);
    try {
      const data = await enqueueSyncJob(
        "/positions/sync/intraday-tws",
        "Refresh live intraday overlay from trade group view.",
      );
      setMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      // Refresh once the worker reports the job finished.
      watch(data.job_id, () => onDone());
    } catch (err) {
      setMessage(errorMessage(err, "Unknown sync error"));
    } finally {
      setSyncing(false);
    }
  }, [watch, onDone]);

  return { syncing, message, kickOff };
}
