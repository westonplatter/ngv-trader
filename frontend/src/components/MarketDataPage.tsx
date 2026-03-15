import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";
import { useSSE, type ConnectionStatus } from "../lib/events";

interface Job {
  id: number;
  job_type: string;
  status: string;
  payload: Record<string, unknown>;
  result: Record<string, unknown> | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  last_error: string | null;
}

const STATUS_CLASS: Record<string, string> = {
  queued: "text-yellow-700 bg-yellow-100",
  running: "text-blue-700 bg-blue-100",
  completed: "text-green-700 bg-green-100",
  failed: "text-red-700 bg-red-100",
};

const MARKET_DATA_JOB_TYPES = [
  "contracts.chain_sync",
  "contracts.qualify_and_snapshot",
  "market_data.futures_prices",
  "market_data.futures_options",
  "market_data.snapshot",
];

interface JobPreset {
  label: string;
  job_type: string;
  payload: Record<string, unknown>;
  useFilter?: boolean;
}

interface ChainSyncPreset {
  label: string;
  symbol: string;
  front_n: number;
}

const CHAIN_SYNC_PRESETS: ChainSyncPreset[] = [
  { label: "Sync CL chain", symbol: "CL", front_n: 12 },
  { label: "Sync ES chain", symbol: "ES", front_n: 5 },
  { label: "Sync NQ chain", symbol: "NQ", front_n: 5 },
];

const PRESETS: JobPreset[] = [
  {
    label: "CL futures prices",
    job_type: "market_data.futures_prices",
    payload: { symbol: "CL", front_n: 12 },
  },
  {
    label: "ES futures prices",
    job_type: "market_data.futures_prices",
    payload: { symbol: "ES", front_n: 5 },
  },
  {
    label: "CL options (filtered)",
    job_type: "market_data.futures_options",
    payload: { symbol: "CL" },
    useFilter: true,
  },
  {
    label: "ES options (filtered)",
    job_type: "market_data.futures_options",
    payload: { symbol: "ES" },
    useFilter: true,
  },
];

interface PendingFilterJob {
  preset: JobPreset;
  futPrice: number | null;
  filterConfig: Record<string, unknown>;
  payload: Record<string, unknown>;
}

function formatAge(isoStr: string): string {
  const ms = Date.now() - Date.parse(isoStr);
  if (ms < 0) return "just now";
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}

function StepperField({
  label,
  value,
  step,
  onChange,
}: {
  label: string;
  value: number | null;
  step: number;
  onChange: (v: number | null) => void;
}) {
  const display = value != null ? String(value) : "—";
  return (
    <div className="flex items-center gap-1">
      <span className="mr-1 text-xs font-medium text-blue-800">{label}</span>
      <button
        onClick={() =>
          onChange(value != null ? +(value - step).toFixed(10) : 0)
        }
        className="rounded border border-blue-300 bg-white px-1.5 py-0.5 text-xs font-bold text-blue-700 hover:bg-blue-100"
      >
        −
      </button>
      <input
        type="number"
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? null : Number(e.target.value))
        }
        step={step}
        className="w-20 rounded border border-blue-300 bg-white px-1.5 py-0.5 text-center font-mono text-xs text-gray-800"
      />
      <button
        onClick={() =>
          onChange(value != null ? +(value + step).toFixed(10) : 0)
        }
        className="rounded border border-blue-300 bg-white px-1.5 py-0.5 text-xs font-bold text-blue-700 hover:bg-blue-100"
      >
        +
      </button>
    </div>
  );
}

export default function MarketDataPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Custom job form
  const [customType, setCustomType] = useState(MARKET_DATA_JOB_TYPES[0]);
  const [customPayload, setCustomPayload] = useState("{}");

  // Confirm-before-enqueue state for filtered jobs
  const [pendingFilter, setPendingFilter] = useState<PendingFilterJob | null>(
    null,
  );
  const [strikeGte, setStrikeGte] = useState<number | null>(null);
  const [strikeLte, setStrikeLte] = useState<number | null>(null);
  const [dteLte, setDteLte] = useState<number | null>(null);
  const [modulus, setModulus] = useState<number | null>(null);

  const prevStatusRef = useRef<ConnectionStatus | null>(null);

  const loadJobs = useCallback(() => {
    fetch(`${API_BASE_URL}/jobs?include_archived=false`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: Job[]) => {
        setJobs(rows.filter((j) => MARKET_DATA_JOB_TYPES.includes(j.job_type)));
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  // Initial fetch on mount.
  useEffect(() => {
    loadJobs();
  }, [loadJobs]);

  // Merge SSE job events (only for market-data job types).
  const handleJobEvent = useCallback((payload: Job, eventType: string) => {
    if (!MARKET_DATA_JOB_TYPES.includes(payload.job_type)) return;
    if (eventType === "job.archived") {
      setJobs((prev) => prev.filter((j) => j.id !== payload.id));
      return;
    }
    setJobs((prev) => {
      const idx = prev.findIndex((j) => j.id === payload.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = payload;
        return next;
      }
      return [payload, ...prev];
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

  const enqueueJob = async (
    jobType: string,
    payload: Record<string, unknown>,
  ) => {
    const key = `${jobType}-${JSON.stringify(payload)}`;
    setSubmitting(key);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_type: jobType, payload, source: "ui" }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const job = await res.json();
      setMessage(`Job #${job.id} enqueued (${jobType})`);
      loadJobs();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(null);
    }
  };

  const rerunJob = async (jobId: number) => {
    setSubmitting(`rerun-${jobId}`);
    setMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/rerun`, {
        method: "POST",
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const job = await res.json();
      setMessage(`Job #${job.id} enqueued (rerun of #${jobId})`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(null);
    }
  };

  const archiveJob = async (jobId: number) => {
    setSubmitting(`archive-${jobId}`);
    try {
      const res = await fetch(`${API_BASE_URL}/jobs/${jobId}/archive`, {
        method: "POST",
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(null);
    }
  };

  const handlePreset = async (preset: JobPreset) => {
    if (preset.useFilter) {
      const symbol = preset.payload.symbol as string;
      try {
        setSubmitting(preset.label);
        setError(null);
        const res = await fetch(
          `${API_BASE_URL}/futures/${symbol}/option-filter`,
        );
        if (!res.ok) throw new Error(`Filter fetch failed: HTTP ${res.status}`);
        const filter = await res.json();
        const payload: Record<string, unknown> = { ...preset.payload };
        if (filter.computed.strike_gte != null)
          payload.strike_gte = filter.computed.strike_gte;
        if (filter.computed.strike_lte != null)
          payload.strike_lte = filter.computed.strike_lte;
        if (filter.computed.dte_lte != null)
          payload.dte_lte = filter.computed.dte_lte;

        setPendingFilter({
          preset,
          futPrice: filter.fut_price,
          filterConfig: filter.filter_config,
          payload,
        });
        setStrikeGte(filter.computed.strike_gte);
        setStrikeLte(filter.computed.strike_lte);
        setDteLte(filter.computed.dte_lte);
        setModulus(Number(filter.filter_config.modulus_eq) || 1);
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setSubmitting(null);
      }
    } else {
      enqueueJob(preset.job_type, preset.payload);
    }
  };

  const handleConfirmFilter = () => {
    if (!pendingFilter) return;
    const payload: Record<string, unknown> = {
      ...pendingFilter.preset.payload,
    };
    if (strikeGte != null) payload.strike_gte = strikeGte;
    if (strikeLte != null) payload.strike_lte = strikeLte;
    if (dteLte != null) payload.dte_lte = dteLte;
    if (modulus != null) payload.modulus_eq = modulus;
    setPendingFilter(null);
    enqueueJob(pendingFilter.preset.job_type, payload);
  };

  const handleCancelFilter = () => {
    setPendingFilter(null);
  };

  const handleCustomSubmit = () => {
    try {
      const parsed = JSON.parse(customPayload);
      enqueueJob(customType, parsed);
    } catch {
      setError("Invalid JSON payload");
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <h1 className="text-lg font-bold text-gray-900">Market Data</h1>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
          <button
            onClick={() => setError(null)}
            className="ml-2 text-xs underline"
          >
            dismiss
          </button>
        </div>
      )}
      {message && (
        <div className="rounded border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
          {message}
        </div>
      )}

      {/* Quick actions */}
      <section className="rounded border border-gray-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-gray-800">
          Quick Actions
        </h2>
        <div className="flex flex-wrap gap-2 items-center">
          {/* Chain sync */}
          {CHAIN_SYNC_PRESETS.map((preset) => (
            <button
              key={preset.symbol}
              onClick={() =>
                enqueueJob("contracts.chain_sync", {
                  symbol: preset.symbol,
                  front_n: preset.front_n,
                })
              }
              disabled={submitting !== null || pendingFilter !== null}
              className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {preset.label}
            </button>
          ))}
          {/* Other presets */}
          {PRESETS.map((preset) => (
            <button
              key={preset.label}
              onClick={() => handlePreset(preset)}
              disabled={submitting !== null || pendingFilter !== null}
              className="rounded border border-gray-300 px-3 py-1.5 text-xs text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {preset.label}
            </button>
          ))}
        </div>
      </section>

      {/* Confirm filtered job */}
      {pendingFilter && (
        <section className="rounded border border-blue-300 bg-blue-50 p-4">
          <h2 className="mb-2 text-sm font-semibold text-blue-900">
            Confirm: {pendingFilter.preset.label}
          </h2>
          <div className="mb-3 text-xs text-blue-800">
            <span className="font-medium">FUT price:</span>{" "}
            {pendingFilter.futPrice != null
              ? pendingFilter.futPrice.toFixed(2)
              : "N/A"}
            <span className="ml-3 font-medium">Config:</span>{" "}
            {Object.entries(pendingFilter.filterConfig)
              .map(([k, v]) => `${k}=${v}`)
              .join(", ")}
          </div>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <StepperField
              label="strike_gte"
              value={strikeGte}
              step={modulus || 1}
              onChange={setStrikeGte}
            />
            <StepperField
              label="strike_lte"
              value={strikeLte}
              step={modulus || 1}
              onChange={setStrikeLte}
            />
            <StepperField
              label="dte_lte"
              value={dteLte}
              step={1}
              onChange={setDteLte}
            />
            <StepperField
              label="modulus"
              value={modulus}
              step={modulus && modulus >= 1 ? 1 : 0.5}
              onChange={setModulus}
            />
          </div>
          <div className="flex gap-2">
            <button
              onClick={handleConfirmFilter}
              disabled={submitting !== null}
              className="rounded border border-blue-600 bg-blue-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Enqueue
            </button>
            <button
              onClick={handleCancelFilter}
              className="rounded border border-gray-300 px-4 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </section>
      )}

      {/* Custom job */}
      <section className="rounded border border-gray-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-semibold text-gray-800">Custom Job</h2>
        <div className="flex items-end gap-2">
          <div>
            <label className="mb-1 block text-xs text-gray-600">Job Type</label>
            <select
              value={customType}
              onChange={(e) => setCustomType(e.target.value)}
              className="rounded border border-gray-300 px-2 py-1.5 text-sm"
            >
              {MARKET_DATA_JOB_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-xs text-gray-600">
              Payload (JSON)
            </label>
            <input
              type="text"
              value={customPayload}
              onChange={(e) => setCustomPayload(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1.5 font-mono text-sm"
            />
          </div>
          <button
            onClick={handleCustomSubmit}
            disabled={submitting !== null}
            className="rounded border border-blue-300 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            Enqueue
          </button>
        </div>
      </section>

      {/* Jobs table */}
      <section className="rounded border border-gray-200 bg-white p-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-800">
            Market Data Jobs
          </h2>
        </div>
        <div className="overflow-auto">
          <table className="min-w-full border-collapse text-xs">
            <thead>
              <tr className="bg-gray-100 text-left">
                <th className="px-2 py-1 font-semibold text-gray-700">ID</th>
                <th className="px-2 py-1 font-semibold text-gray-700">Type</th>
                <th className="px-2 py-1 font-semibold text-gray-700">
                  Status
                </th>
                <th className="px-2 py-1 font-semibold text-gray-700">
                  Created
                </th>
                <th className="px-2 py-1 font-semibold text-gray-700">
                  Payload
                </th>
                <th className="px-2 py-1 font-semibold text-gray-700">
                  Result / Error
                </th>
                <th className="px-2 py-1 font-semibold text-gray-700">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 && (
                <tr>
                  <td className="px-2 py-3 text-gray-500" colSpan={7}>
                    No market data jobs yet. Use the actions above to enqueue
                    one.
                  </td>
                </tr>
              )}
              {jobs.map((job) => (
                <tr key={job.id} className="border-b border-gray-200 align-top">
                  <td className="px-2 py-1 font-mono text-gray-800">
                    {job.id}
                  </td>
                  <td className="px-2 py-1 text-gray-700">{job.job_type}</td>
                  <td className="px-2 py-1">
                    <span
                      className={`rounded px-1.5 py-0.5 ${STATUS_CLASS[job.status] ?? "text-gray-700 bg-gray-100"}`}
                    >
                      {job.status}
                    </span>
                  </td>
                  <td className="px-2 py-1 text-gray-600">
                    {formatAge(job.created_at)}
                  </td>
                  <td className="max-w-[200px] truncate px-2 py-1 font-mono text-gray-600">
                    {JSON.stringify(job.payload)}
                  </td>
                  <td className="max-w-[250px] truncate px-2 py-1 font-mono text-gray-600">
                    {job.status === "failed"
                      ? job.last_error
                      : job.result
                        ? JSON.stringify(job.result)
                        : "—"}
                  </td>
                  <td className="px-2 py-1">
                    <div className="flex gap-1">
                      <button
                        onClick={() => rerunJob(job.id)}
                        disabled={submitting !== null}
                        className="rounded border border-blue-300 px-1.5 py-0.5 text-xs text-blue-700 hover:bg-blue-50 disabled:opacity-50"
                        title="Rerun this job"
                      >
                        Rerun
                      </button>
                      <button
                        onClick={() => archiveJob(job.id)}
                        disabled={submitting !== null}
                        className="rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-500 hover:bg-gray-50 hover:text-red-600 disabled:opacity-50"
                        title="Archive this job"
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
      </section>
    </div>
  );
}
