// Typed calls to the backend API: one `request` that throws the server's
// `detail` on failure, and a `query` that drops empty params. New API modules
// (see ./tags.ts) build on these instead of calling `fetch` directly.

import { API_BASE_URL } from "../config";

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${method} ${path} failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // keep the generic message
    }
    throw new Error(detail);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

export type QueryValue =
  | string
  | number
  | boolean
  | string[]
  | null
  | undefined;

// "?a=1&b=x&b=y" from a params object; null, undefined, and "" are left out.
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

// The message to show for a failed request.
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
