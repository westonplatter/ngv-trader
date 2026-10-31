// The three manual syncs the Positions toolbar can queue, with one busy flag
// per kind so each button disables independently, and one shared message and
// error line. `onDone` runs when the job watcher reports the job finished.

import { useCallback, useState } from "react";
import { enqueueSyncJob, useJobWatcher } from "../../hooks/useJobWatcher";
import type { QueuedJob } from "../../hooks/useJobWatcher";
import { errorMessage } from "../../lib/api";

export type SyncKind = "flex" | "intraday" | "metrics";

const SYNC_JOBS: Record<
  SyncKind,
  { path: string; requestText: string; queued: (job: QueuedJob) => string }
> = {
  flex: {
    path: "/positions/sync/flex-query",
    requestText: "Kick off flex query positions sync from Positions page.",
    queued: (job) => `Queued positions sync job #${job.job_id} (${job.status}).`,
  },
  intraday: {
    path: "/positions/sync/intraday-tws",
    requestText: "Refresh live intraday overlay from Positions page.",
    queued: (job) =>
      `Queued intraday TWS sync job #${job.job_id} (${job.status}). Refreshing shortly…`,
  },
  metrics: {
    path: "/positions/sync/option-metrics-tws",
    requestText: "Refresh live option metrics from Positions page.",
    queued: (job) =>
      `Queued option-metrics TWS sync job #${job.job_id} (${job.status}). Refreshing shortly…`,
  },
};

export interface PositionSync {
  busy: Record<SyncKind, boolean>;
  message: string | null;
  error: string | null;
  kickOff: (kind: SyncKind) => Promise<void>;
}

export function usePositionSync(onDone: () => void): PositionSync {
  const { watch } = useJobWatcher();
  const [busy, setBusy] = useState<Record<SyncKind, boolean>>({
    flex: false,
    intraday: false,
    metrics: false,
  });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const kickOff = useCallback(
    async (kind: SyncKind) => {
      const job = SYNC_JOBS[kind];
      setBusy((current) => ({ ...current, [kind]: true }));
      setError(null);
      setMessage(null);
      try {
        const data = await enqueueSyncJob(job.path, job.requestText);
        setMessage(job.queued(data));
        watch(data.job_id, () => onDone());
      } catch (err) {
        setError(errorMessage(err, "Unknown sync error"));
      } finally {
        setBusy((current) => ({ ...current, [kind]: false }));
      }
    },
    [watch, onDone],
  );

  return { busy, message, error, kickOff };
}
