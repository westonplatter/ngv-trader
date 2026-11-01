// The manual syncs the Trades toolbar can queue: FlexQuery trade syncs over a
// window (days, since the last trade, or an explicit date range) and the
// intraday TWS pull. Each job is watched to completion so the table reloads
// and a browser notification fires when it finishes.

import { useCallback, useState } from "react";
import { enqueueSyncJob, useJobWatcher } from "../../hooks/useJobWatcher";
import { errorMessage } from "../../lib/api";

export interface TradesSyncOptions {
  days?: number;
  sinceLastTrade?: boolean;
  startDate?: string;
  endDate?: string;
}

export interface TradeSync {
  // True while a request to enqueue is in flight (not while the job runs).
  syncing: boolean;
  message: string | null;
  error: string | null;
  kickOffTradesSync: (label: string, options: TradesSyncOptions) => Promise<void>;
  kickOffIntradaySync: () => Promise<void>;
}

function notifyJobDone(message: string): void {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "granted") {
    new Notification("NextGenTrader", { body: message });
  }
}

export function useTradeSync(onDone: () => void): TradeSync {
  const { watch } = useJobWatcher();
  const [syncing, setSyncing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Watches the job until it reaches a terminal state, then surfaces a
  // notification and refreshes the table (no full page reload needed).
  const watchJobUntilDone = useCallback(
    (jobId: number, label: string) => {
      if (
        typeof Notification !== "undefined" &&
        Notification.permission === "default"
      ) {
        void Notification.requestPermission().catch(() => {});
      }
      watch(jobId, (job) => {
        const finished =
          job.status === "completed"
            ? `${label} job #${jobId} completed.`
            : `${label} job #${jobId} failed${
                job.last_error ? `: ${job.last_error}` : "."
              }`;
        if (job.status === "completed") {
          setMessage(finished);
        } else {
          setError(finished);
        }
        notifyJobDone(finished);
        onDone();
      });
    },
    [watch, onDone],
  );

  const kickOffTradesSync = useCallback(
    async (label: string, options: TradesSyncOptions) => {
      setSyncing(true);
      setMessage(null);
      setError(null);
      try {
        const data = await enqueueSyncJob<{
          job_id: number;
          status: string;
          start_date?: string | null;
          end_date?: string | null;
        }>(
          "/trades/sync/flex-query",
          `${label} (flex query) from Trades page.`,
          {
            ...(options.days !== undefined ? { days: options.days } : {}),
            ...(options.sinceLastTrade ? { since_last_trade: true } : {}),
            ...(options.startDate && options.endDate
              ? { start_date: options.startDate, end_date: options.endDate }
              : {}),
          },
          "Unable to queue sync",
        );
        const rangeNote =
          data.start_date && data.end_date
            ? ` Syncing ${data.start_date} → ${data.end_date}.`
            : "";
        setMessage(
          `Queued ${label.toLowerCase()} job #${data.job_id} (${data.status}).${rangeNote}`,
        );
        watchJobUntilDone(data.job_id, label);
      } catch (err) {
        setError(errorMessage(err, "Unknown sync error"));
      } finally {
        setSyncing(false);
      }
    },
    [watchJobUntilDone],
  );

  const kickOffIntradaySync = useCallback(async () => {
    setSyncing(true);
    setMessage(null);
    setError(null);
    try {
      const data = await enqueueSyncJob(
        "/positions/sync/intraday-tws",
        "Intraday TWS sync from Trades page.",
        {},
        "Unable to queue intraday sync",
      );
      setMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}).`,
      );
      watchJobUntilDone(data.job_id, "Intraday TWS sync");
    } catch (err) {
      setError(errorMessage(err, "Unknown sync error"));
    } finally {
      setSyncing(false);
    }
  }, [watchJobUntilDone]);

  return { syncing, message, error, kickOffTradesSync, kickOffIntradaySync };
}
