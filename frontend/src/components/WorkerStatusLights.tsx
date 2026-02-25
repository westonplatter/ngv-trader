import { useEffect, useState } from "react";

type LightColor = "green" | "yellow" | "red";

interface WorkerStatus {
  worker_type: string;
  light: LightColor;
  status: string;
  heartbeat_at: string | null;
  seconds_since_heartbeat: number | null;
  details: string | null;
}

const KNOWN_WORKERS = ["jobs"] as const;

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

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch("http://localhost:8000/api/v1/workers/status")
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((rows: WorkerStatus[]) => {
          if (!active) return;
          const next: Record<string, WorkerStatus> = {};
          rows.forEach((row) => {
            next[row.worker_type] = row;
          });
          setStatusMap(next);
        })
        .catch(() => {
          if (!active) return;
          const next: Record<string, WorkerStatus> = {};
          KNOWN_WORKERS.forEach((workerType) => {
            next[workerType] = fallbackStatus(workerType);
          });
          setStatusMap(next);
        });
    };

    load();
    const timer = window.setInterval(load, 4000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

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
            <span>Worker Jobs</span>
          </div>
        );
      })}
    </div>
  );
}
