// Shared HTTP client for the FastAPI backend.
//
// Every call to the API goes through `request` (directly, or via a resource
// module such as `tagsApi` in ./tags) so URL building, JSON encoding, and error
// surfacing happen one way. Components set page-level error state from the
// thrown message and never look at a raw Response.
//
// Demo mode (./demoApi) patches `window.fetch` for URLs under API_BASE_URL, so
// this client works unchanged against the static fixtures.

import { API_BASE_URL } from "../config";

export class ApiError extends Error {
  readonly status: number;
  // The FastAPI `detail` string when the error body carried one.
  readonly detail: string | null;

  constructor(message: string, status: number, detail: string | null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  // User-facing message when the error body has no `detail`. Defaults to
  // "<METHOD> <path> failed".
  fallback?: string;
}

type QueryValue = string | number | boolean | string[] | null | undefined;

// Build a query string, skipping null/undefined/empty values and repeating a
// key for array values (`?all=a&all=b`). Returns "" when nothing survives.
export function query(params: Record<string, QueryValue>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

async function readDetail(response: Response): Promise<string | null> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") return payload.detail;
  } catch {
    // Non-JSON error body: nothing readable to surface.
  }
  return null;
}

// Message for a non-2xx response: the backend `detail` when there is one, else
// `fallback`, always suffixed with the status so the operator can tell which
// failure it was. Exported for the few call sites that still hold a Response.
export async function readErrorMessage(
  response: Response,
  fallback: string,
): Promise<string> {
  const detail = await readDetail(response);
  return `${detail ?? fallback} (${response.status})`;
}

// Send one request and parse the JSON body. Throws ApiError on a non-2xx
// status; a 204 resolves to undefined. `body` is JSON-encoded when given.
export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  });
  if (!response.ok) {
    const detail = await readDetail(response);
    const fallback = options.fallback ?? `${method} ${path} failed`;
    throw new ApiError(
      `${detail ?? fallback} (${response.status})`,
      response.status,
      detail,
    );
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
