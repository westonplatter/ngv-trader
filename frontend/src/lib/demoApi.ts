// Demo API transport.
//
// When demo mode is on (see ./demoMode), this replaces the API client's
// transport (see ./api `setApiFetch`) so any request to the backend API is
// answered from static fixtures (./demoData) instead of hitting the network.
// Components keep calling `api.*` exactly as they do against a live backend —
// no per-component demo branches required, and the global `fetch` is untouched.
//
// Only requests under API_BASE_URL are intercepted; anything else the client is
// pointed at (the pricing service, say) falls through to the real network.
// Server-Sent Events use EventSource, not the client, so they simply fail to
// connect in demo mode and the UI degrades gracefully to its last-known state.

import { API_BASE_URL } from "../config";
import { setApiFetch, type ApiFetch } from "./api";
import {
  DEMO_ACCOUNTS,
  DEMO_FLEXQUERY_TOKENS,
  DEMO_POSITIONS,
  DEMO_STRATEGIES,
  DEMO_TRADE_EXECUTIONS,
  demoGroupExecutions,
  demoTradeGroupDetail,
  demoTradeGroupRows,
} from "./demoData";
import {
  demoTagList,
  demoTagSearch,
  demoTaskList,
  withGroupTags,
  withPositionTags,
  withTradeTags,
} from "./demoTags";

type Json = unknown;

function splitOnce(value: string, separator: string): [string, string?] {
  const index = value.indexOf(separator);
  if (index === -1) return [value];
  return [value.slice(0, index), value.slice(index + separator.length)];
}

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

// Resolve a GET request path (stripped of the API base) plus its query params
// to a fixture payload. Returns undefined when no fixture matches.
function routeGet(path: string, params: URLSearchParams): Json | undefined {
  if (path === "/positions") return withPositionTags(DEMO_POSITIONS);
  if (path === "/accounts") return DEMO_ACCOUNTS;
  if (path === "/flexquery-tokens") return DEMO_FLEXQUERY_TOKENS;
  if (path === "/workers/status") return demoWorkerStatuses();
  if (path === "/strategies") return DEMO_STRATEGIES;
  if (path === "/trade-groups") {
    return demoTradeGroupRows({
      status: params.get("status"),
      accountId: params.get("account_id"),
      instrument: params.get("instrument"),
      includeIntraday: params.get("include_intraday") === "true",
    }).map(withGroupTags);
  }
  if (path === "/trade-executions") return withTradeTags(DEMO_TRADE_EXECUTIONS);
  if (path === "/tags") {
    const q = (params.get("q") ?? "").trim().toLowerCase();
    return demoTagList().filter((tag) => tag.normalized_value.includes(q));
  }
  if (path === "/tags/search") return demoTagSearch(params);
  if (path === "/tasks") return demoTaskList(params);

  // Sync buttons watch the job they queued; answer as already finished so the
  // page refreshes once instead of polling a backend that is not there.
  const jobMatch = path.match(/^\/jobs\/(\d+)$/);
  if (jobMatch) {
    return {
      id: Number(jobMatch[1]),
      job_type: "demo",
      status: "completed",
      result: null,
      last_error: null,
    };
  }

  const execMatch = path.match(/^\/trade-groups\/(\d+)\/executions$/);
  if (execMatch) return demoGroupExecutions(Number(execMatch[1])) ?? undefined;

  const detailMatch = path.match(/^\/trade-groups\/(\d+)$/);
  if (detailMatch) {
    const detail = demoTradeGroupDetail(Number(detailMatch[1]));
    return detail ? withGroupTags(detail) : undefined;
  }

  return undefined;
}

function handle(
  method: string,
  path: string,
  params: URLSearchParams,
): Response {
  if (method === "GET") {
    const body = routeGet(path, params);
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

  const realFetch: ApiFetch = (input, init) => window.fetch(input, init);

  const demoFetch: ApiFetch = async (url, init) => {
    if (url.startsWith(API_BASE_URL)) {
      const method = (init?.method ?? "GET").toUpperCase();
      const [path, search = ""] = splitOnce(
        url.slice(API_BASE_URL.length),
        "?",
      );
      return handle(method, path, new URLSearchParams(search));
    }
    return realFetch(url, init);
  };

  setApiFetch(demoFetch);
}
