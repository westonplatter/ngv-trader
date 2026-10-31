import { useCallback, useMemo } from "react";
import { useSseList } from "../hooks/useSseList";
import { api } from "../lib/api";

type LightColor = "green" | "yellow" | "red";

interface WorkerStatus {
  worker_type: string;
  light: LightColor;
  status: string;
  heartbeat_at: string | null;
  seconds_since_heartbeat: number | null;
  details: string | null;
}

const KNOWN_WORKERS = ["jobs", "orders"] as const;

const LIGHT_CLASS: Record<LightColor, string> = {
  green: "bg-green-500",
  yellow: "bg-yellow-500",
  red: "bg-red-500",
};

function fallbackStatus(workerType: string): WorkerStatus {
  return {
    worker_type: workerType,
    light: "red",
    status: "unknown",
    heartbeat_at: null,
    seconds_since_heartbeat: null,
    details: "No data",
  };
}

function formatAge(seconds: number | null): string {
  if (seconds === null) return "n/a";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.round(seconds / 60)}m`;
}

export default function WorkerStatusLights() {
  // On a failed load every known worker shows the red fallback.
  const loadStatuses = useCallback(
    () =>
      api
        .get<WorkerStatus[]>("/workers/status")
        .catch(() => KNOWN_WORKERS.map(fallbackStatus)),
    [],
  );

  // Snapshot on mount, upsert heartbeats from the stream, re-fetch on reconnect.
  const { items } = useSseList<WorkerStatus>({
    topic: "worker_status",
    load: loadStatuses,
    key: (row) => row.worker_type,
  });

  const statusMap = useMemo(() => {
    const next: Record<string, WorkerStatus> = {};
    items.forEach((row) => {
      next[row.worker_type] = row;
    });
    return next;
  }, [items]);

  return (
    <div className="ml-auto flex items-center gap-4">
      {KNOWN_WORKERS.map((workerType) => {
        const row = statusMap[workerType] ?? fallbackStatus(workerType);
        return (
          <div
            key={workerType}
            className="inline-flex items-center gap-2 text-xs text-gray-600"
            title={`${row.status} (${formatAge(row.seconds_since_heartbeat)} ago) ${row.details ?? ""}`}
          >
            <span
              className={`inline-block h-2.5 w-2.5 rounded-full ${LIGHT_CLASS[row.light]}`}
            />
            <span className="capitalize">Worker {workerType}</span>
            <span className="rounded bg-gray-100 px-1.5 py-0.5 font-medium text-gray-700">
              {row.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}
