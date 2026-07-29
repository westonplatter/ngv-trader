import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE_URL } from "../config";
import { useSSE, type ConnectionStatus } from "../lib/events";

interface Job {
  id: number;
  job_type: string;
  status: string;
  payload: Record<string, unknown> | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  archived_at: string | null;
  last_error: string | null;
}

const STATUS_CLASS: Record<string, string> = {
  queued: "text-yellow-700 bg-yellow-100",
  running: "text-blue-700 bg-blue-100",
  completed: "text-green-700 bg-green-100",
  failed: "text-red-700 bg-red-100",
};

function parseTime(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

function computeQueueMs(job: Job, nowMs: number): number {
  const createdMs = parseTime(job.created_at) ?? nowMs;
  const startedMs = parseTime(job.started_at);
  return (startedMs ?? nowMs) - createdMs;
}

function computeRunMs(job: Job, nowMs: number): number | null {
  const startedMs = parseTime(job.started_at);
  if (startedMs === null) return null;
  const completedMs = parseTime(job.completed_at);
  return (completedMs ?? nowMs) - startedMs;
}

function computeTotalMs(job: Job, nowMs: number): number {
  const createdMs = parseTime(job.created_at) ?? nowMs;
  const completedMs = parseTime(job.completed_at);
  return (completedMs ?? nowMs) - createdMs;
}

function formatParamValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// Render a job's payload as compact key=value chips. trade_group_id is special-
// cased to a deep link into the tagging page for that group.
function ParamsCell({ payload }: { payload: Job["payload"] }) {
  const entries = Object.entries(payload ?? {});
  if (entries.length === 0) {
    return <span className="text-gray-400">—</span>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([key, value]) => {
        if (key === "trade_group_id" && value != null) {
          return (
            <Link
              key={key}
              to={`/tagging?trade_group_id=${String(value)}`}
              className="rounded bg-indigo-100 px-1.5 py-0.5 font-mono text-[11px] text-indigo-700 hover:bg-indigo-200 hover:underline"
            >
              trade-group-{String(value)}
            </Link>
          );
        }
        return (
          <span
            key={key}
            className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-600"
            title={`${key}=${formatParamValue(value)}`}
          >
            {key}={formatParamValue(value)}
          </span>
        );
      })}
    </div>
  );
}

export default function JobsTable() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  const [actioning, setActioning] = useState<Set<number>>(new Set());

  // Track previous SSE status so we can detect reconnect transitions.
  const prevStatusRef = useRef<ConnectionStatus | null>(null);

  const loadJobs = useCallback(() => {
    fetch(`${API_BASE_URL}/jobs`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: Job[]) => {
        setJobs(rows.slice(0, 20));
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  // Initial fetch on mount.
  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Merge an incoming SSE job payload into the jobs list.
  const handleJobEvent = useCallback((payload: Job, eventType: string) => {
    if (eventType === "job.archived") {
      setJobs((prev) => prev.filter((j) => j.id !== payload.id));
      return;
    }
    setJobs((prev) => {
      const idx = prev.findIndex((j) => j.id === payload.id);
      let next: Job[];
      if (idx >= 0) {
        next = [...prev];
        next[idx] = payload;
      } else {
        next = [payload, ...prev];
      }
      return next.slice(0, 20);
    });
  }, []);

  const sseStatus = useSSE<Job>("jobs", handleJobEvent);

  // Re-fetch REST snapshot on reconnect.
  useEffect(() => {
    if (prevStatusRef.current === "disconnected" && sseStatus === "connected") {
      loadJobs();
    }
    prevStatusRef.current = sseStatus;
  }, [sseStatus, loadJobs]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const reload = loadJobs;

  const withAction = (jobId: number, action: () => Promise<void>) => {
    setActioning((prev) => {
      const next = new Set(prev);
      next.add(jobId);
      return next;
    });
    action()
      .then(() => reload())
      .catch((err: Error) => setError(err.message))
      .finally(() => {
        setActioning((prev) => {
          const next = new Set(prev);
          next.delete(jobId);
          return next;
        });
      });
  };

  const rerunJob = (jobId: number) =>
    withAction(jobId, async () => {
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/rerun`, {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
    });

  const archiveJob = (jobId: number) =>
    withAction(jobId, async () => {
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/archive`, {
        method: "POST",
      });
      if (!res.ok) {
        throw new Error(await res.text());
      }
    });

  return (
    <div className="min-w-0 h-full min-h-0 rounded border border-gray-300 bg-white p-3 flex flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Jobs</h3>
      </div>

      {error && <p className="mb-2 text-xs text-red-600">Error: {error}</p>}

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="min-w-full border-collapse text-xs">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-2 py-1 font-semibold text-gray-700">ID</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Type</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Params</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Status</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Queue</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Run</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Total</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 && (
              <tr>
                <td className="px-2 py-2 text-gray-500" colSpan={8}>
                  No jobs yet.
                </td>
              </tr>
            )}
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-gray-200 align-top">
                <td className="px-2 py-1 font-mono text-gray-800">{job.id}</td>
                <td className="px-2 py-1 text-gray-700">{job.job_type}</td>
                <td className="px-2 py-1">
                  <ParamsCell payload={job.payload} />
                </td>
                <td className="px-2 py-1">
                  <span
                    className={`rounded px-1.5 py-0.5 ${STATUS_CLASS[job.status] ?? "text-gray-700 bg-gray-100"}`}
                    title={
                      job.last_error ??
                      `attempts ${job.attempts}/${job.max_attempts}`
                    }
                  >
                    {job.status}
                  </span>
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeQueueMs(job, nowMs))}
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeRunMs(job, nowMs))}
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeTotalMs(job, nowMs))}
                </td>
                <td className="px-2 py-1 whitespace-nowrap">
                  <div className="flex gap-1">
                    {job.status === "failed" && (
                      <button
                        onClick={() => rerunJob(job.id)}
                        disabled={actioning.has(job.id)}
                        className="rounded border border-blue-300 px-1.5 py-0.5 text-[11px] text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                      >
                        Rerun
                      </button>
                    )}
                    <button
                      onClick={() => archiveJob(job.id)}
                      disabled={actioning.has(job.id)}
                      className="rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-100 disabled:opacity-50"
                    >
                      Archive
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
