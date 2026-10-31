// Kick off a background job and find out when it finishes.
//
// Pages used to POST a sync endpoint and then refresh on fixed timers (3s and
// 8s) or hand-roll a `GET /jobs/:id` poll. Job state already arrives on the
// `jobs` SSE topic, so this watches that stream for the job's terminal status.
// The stream is the fast path; polling is the safety net. The worker's "job
// updated" notify is best-effort, so a lost one must not strand a page: while
// the stream is down a watch is polled every 2s, and while it is up, every 10s.

import { useCallback, useEffect, useRef } from "react";
import { api } from "../lib/api";
import { useSSE } from "../lib/events";

export const JOB_SOURCE_UI = "manual-ui";
export const DEFAULT_JOB_MAX_ATTEMPTS = 3;

// What the sync endpoints return after enqueuing.
export interface QueuedJob {
  job_id: number;
  status: string;
}

// The fields of a job row the watcher needs; the SSE payload and
// `GET /jobs/:id` both carry them.
export interface WatchedJob {
  id: number;
  status: string;
  job_type?: string;
  result?: Record<string, unknown> | null;
  last_error?: string | null;
}

export function isTerminalJobStatus(status: string): boolean {
  return status === "completed" || status === "failed";
}

// POST a `/…/sync/…` endpoint with the body every manual sync sends.
export function enqueueSyncJob<T extends QueuedJob = QueuedJob>(
  path: string,
  requestText: string,
  extra: Record<string, unknown> = {},
  fallback = "Unable to queue job",
): Promise<T> {
  return api.post<T>(
    path,
    {
      source: JOB_SOURCE_UI,
      request_text: requestText,
      max_attempts: DEFAULT_JOB_MAX_ATTEMPTS,
      ...extra,
    },
    { fallback },
  );
}

export type JobDoneHandler = (job: WatchedJob) => void;

export interface WatchOptions {
  // Stop watching after this long; the handler is then never called.
  timeoutMs?: number;
}

const POLL_INTERVAL_MS = 2000;
// While the stream is connected it normally delivers completion; this slow poll
// only covers a notify that never arrived.
const CONNECTED_POLL_INTERVAL_MS = 10_000;
const DEFAULT_TIMEOUT_MS = 5 * 60 * 1000;

interface Watch {
  onDone: JobDoneHandler;
  deadline: number;
  // When this watch was last read from `GET /jobs/:id` (ms since epoch).
  lastChecked: number;
}

// Whether a live watch is due for a `GET /jobs/:id` at `now`.
export function shouldPoll(
  watch: Pick<Watch, "deadline" | "lastChecked">,
  now: number,
  sseConnected: boolean,
): boolean {
  if (now > watch.deadline) return false;
  const interval = sseConnected ? CONNECTED_POLL_INTERVAL_MS : POLL_INTERVAL_MS;
  return now - watch.lastChecked >= interval;
}

// Returns `watch(jobId, onDone)`. `onDone` fires once, with the job row, when
// the job reaches `completed` or `failed`. Several jobs can be watched at once.
export function useJobWatcher(): {
  watch: (
    jobId: number,
    onDone: JobDoneHandler,
    options?: WatchOptions,
  ) => void;
} {
  const watchesRef = useRef<Map<number, Watch>>(new Map());
  const sseConnectedRef = useRef(false);

  const settle = useCallback((job: WatchedJob) => {
    const watch = watchesRef.current.get(job.id);
    if (!watch || !isTerminalJobStatus(job.status)) return;
    watchesRef.current.delete(job.id);
    watch.onDone(job);
  }, []);

  const status = useSSE<WatchedJob>("jobs", (payload, eventType) => {
    if (eventType === "job.archived") return;
    settle(payload);
  });
  useEffect(() => {
    sseConnectedRef.current = status === "connected";
  }, [status]);

  const checkOnce = useCallback(
    async (jobId: number) => {
      try {
        const job = await api.get<WatchedJob>(`/jobs/${jobId}`);
        if (job && typeof job.status === "string") settle(job);
      } catch {
        // transient failure; the next check or the stream will catch it
      }
    },
    [settle],
  );

  // Polling safety net: fast while the stream is down, slow while it is up, and
  // only for live watches. Expired watches are dropped without calling `onDone`.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const now = Date.now();
      for (const [jobId, watch] of watchesRef.current) {
        if (now > watch.deadline) {
          watchesRef.current.delete(jobId);
          continue;
        }
        if (shouldPoll(watch, now, sseConnectedRef.current)) {
          watch.lastChecked = now;
          void checkOnce(jobId);
        }
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [checkOnce]);

  const watch = useCallback(
    (jobId: number, onDone: JobDoneHandler, options: WatchOptions = {}) => {
      const now = Date.now();
      watchesRef.current.set(jobId, {
        onDone,
        deadline: now + (options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
        lastChecked: now,
      });
      // The job may already be done (fast worker, or a stream event that
      // arrived before this call); read it once rather than wait.
      void checkOnce(jobId);
    },
    [checkOnce],
  );

  return { watch };
}
