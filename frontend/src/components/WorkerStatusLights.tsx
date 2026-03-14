import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "../config";
import { useSSE, type ConnectionStatus } from "../lib/events";

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
  const [statusMap, setStatusMap] = useState<Record<string, WorkerStatus>>({});
  const prevStatusRef = useRef<ConnectionStatus | null>(null);

  const loadStatuses = useCallback(() => {
    fetch(`${API_BASE_URL}/workers/status`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((rows: WorkerStatus[]) => {
        const next: Record<string, WorkerStatus> = {};
        rows.forEach((row) => {
          next[row.worker_type] = row;
        });
        setStatusMap(next);
      })
      .catch(() => {
        const next: Record<string, WorkerStatus> = {};
        KNOWN_WORKERS.forEach((workerType) => {
          next[workerType] = fallbackStatus(workerType);
        });
        setStatusMap(next);
      });
  }, []);

  // Initial fetch on mount.
  useEffect(() => {
    loadStatuses();
  }, [loadStatuses]);

  // Merge SSE worker heartbeat events.
  const handleWorkerEvent = useCallback((payload: WorkerStatus) => {
    setStatusMap((prev) => ({
      ...prev,
      [payload.worker_type]: payload,
    }));
  }, []);

  const sseStatus = useSSE<WorkerStatus>("worker_status", handleWorkerEvent);

  // Re-fetch on reconnect.
  useEffect(() => {
    if (prevStatusRef.current === "disconnected" && sseStatus === "connected") {
      loadStatuses();
    }
    prevStatusRef.current = sseStatus;
  }, [sseStatus, loadStatuses]);

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
