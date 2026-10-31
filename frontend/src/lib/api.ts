// The one HTTP client for the backend API. Every component goes through
// `api.*` (or `request`) rather than calling `fetch` directly, so error
// handling, JSON encoding, and the base URL live in one place.
//
// `setApiFetch` swaps the underlying transport. Demo mode uses it to answer
// requests from static fixtures (see ./demoApi) and tests use it to stub the
// network. The global `fetch` is never patched.

import { API_BASE_URL } from "../config";

export type ApiFetch = (
  input: string,
  init?: RequestInit,
) => Promise<Response>;

const realFetch: ApiFetch = (input, init) => fetch(input, init);
let fetchImpl: ApiFetch = realFetch;

// Replace the transport; pass null to restore the real network.
export function setApiFetch(impl: ApiFetch | null): void {
  fetchImpl = impl ?? realFetch;
}

// The transport itself, for callers that need a raw `Response` (the chat
// stream). Honors `setApiFetch`, so demo mode and tests still intercept it.
export const apiFetch: ApiFetch = (input, init) => fetchImpl(input, init);

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// A readable message for a failed response. The API returns `{detail}` for the
// cases a user can cause (duplicate name, bad filter pattern, missing key), so
// prefer that; fall back to a non-empty text body, then `fallback (status)`.
export async function readErrorMessage(
  response: Response,
  fallback?: string,
): Promise<string> {
  const generic = fallback
    ? `${fallback} (${response.status})`
    : `HTTP ${response.status}`;
  let text: string;
  try {
    text = await response.text();
  } catch {
    return generic;
  }
  try {
    const payload = JSON.parse(text) as { detail?: unknown };
    if (payload && typeof payload.detail === "string") return payload.detail;
  } catch {
    // not JSON; fall through to the raw body
  }
  const trimmed = text.trim();
  return trimmed && !trimmed.startsWith("{") && !trimmed.startsWith("<")
    ? trimmed
    : generic;
}

// `err.message` when it is an Error, otherwise the fallback.
export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback;
}

export interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
  // Error-message prefix when the response carries no readable detail.
  fallback?: string;
  // Base URL for a backend other than the main API (e.g. the pricing service).
  base?: string;
}

// Send one request and decode the JSON body. Throws `ApiError` on a non-2xx
// status. A 204 (or an empty body) resolves to `undefined`.
export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, signal, fallback, base = API_BASE_URL } = options;
  const response = await fetchImpl(`${base}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    throw new ApiError(
      await readErrorMessage(response, fallback),
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

type Options = Omit<RequestOptions, "body">;

export const api = {
  get: <T>(path: string, options?: Options) =>
    request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: Options) =>
    request<T>("POST", path, { ...options, body }),
  put: <T>(path: string, body?: unknown, options?: Options) =>
    request<T>("PUT", path, { ...options, body }),
  patch: <T>(path: string, body?: unknown, options?: Options) =>
    request<T>("PATCH", path, { ...options, body }),
  delete: <T>(path: string, body?: unknown, options?: Options) =>
    request<T>("DELETE", path, { ...options, body }),
};

export type QueryValue = string | number | boolean | string[] | null | undefined;

// Build a query string, skipping null/undefined/empty values. Arrays repeat the
// key. Returns "" when nothing survives, otherwise a leading "?".
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
