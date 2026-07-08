// Demo API interceptor.
//
// When demo mode is on (see ./demoMode), this patches the global `fetch` so any
// request to the backend API is answered from static fixtures (./demoData)
// instead of hitting the network. Components keep calling `fetch` exactly as
// they do against a live backend — no per-component demo branches required.
//
// Only requests under API_BASE_URL are intercepted; everything else (Vite
// assets, etc.) falls through to the real fetch. Server-Sent Events use
// EventSource, not fetch, so they simply fail to connect in demo mode and the
// UI degrades gracefully to its last-known state.

import { API_BASE_URL } from "../config";
import {
  DEMO_POSITIONS,
  DEMO_STRATEGIES,
  DEMO_TRADE_GROUPS,
  demoGroupExecutions,
  demoTradeGroupDetail,
} from "./demoData";

type Json = unknown;

function jsonResponse(body: Json, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Healthy worker lights so demo screenshots don't show red "unknown" status.
function demoWorkerStatuses(): Json {
  return ["jobs", "orders"].map((workerType) => ({
    worker_type: workerType,
    light: "green",
    status: "running",
    heartbeat_at: "2026-06-21T14:30:00Z",
    seconds_since_heartbeat: 3,
    details: "demo",
  }));
}

// Resolve a GET request path (already stripped of the API base + query) to a
// fixture payload. Returns undefined when no fixture matches.
function routeGet(path: string): Json | undefined {
  if (path === "/positions") return DEMO_POSITIONS;
  if (path === "/workers/status") return demoWorkerStatuses();
  if (path === "/strategies") return DEMO_STRATEGIES;
  if (path === "/trade-groups") return DEMO_TRADE_GROUPS;

  const execMatch = path.match(/^\/trade-groups\/(\d+)\/executions$/);
  if (execMatch) return demoGroupExecutions(Number(execMatch[1])) ?? undefined;

  const detailMatch = path.match(/^\/trade-groups\/(\d+)$/);
  if (detailMatch) return demoTradeGroupDetail(Number(detailMatch[1])) ?? undefined;

  return undefined;
}

function handle(method: string, path: string): Response {
  if (method === "GET") {
    const body = routeGet(path);
    if (body !== undefined) return jsonResponse(body);
    // Unknown GET: most endpoints return lists, so an empty array yields a
    // clean empty state rather than an error.
    return jsonResponse([]);
  }

  // Writes have no backend in demo mode. The sync trigger returns a job-shaped
  // payload so its UI flow stays intact; everything else gets a benign 200.
  if (path.startsWith("/positions/sync/")) {
    return jsonResponse({ job_id: 0, status: "demo (no backend)" });
  }
  return jsonResponse({ ok: true, demo: true });
}

let installed = false;

export function installDemoApi(): void {
  if (installed || typeof window === "undefined") return;
  installed = true;

  const realFetch = window.fetch.bind(window);

  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;

    if (url.startsWith(API_BASE_URL)) {
      const method = (
        init?.method ??
        (input instanceof Request ? input.method : "GET")
      ).toUpperCase();
      const path = url.slice(API_BASE_URL.length).split("?")[0];
      return handle(method, path);
    }

    return realFetch(input as RequestInfo, init);
  };
}
