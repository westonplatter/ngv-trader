// Shared date/time formatters for the data tables. Companion to number.ts.
//
// Every helper takes the raw API string (ISO timestamp or IBKR YYYYMMDD) and
// returns display text, with an em dash for a missing or unparseable value so
// empty cells look the same on every page.

const MISSING = "—";

/**
 * Contract expiry. IBKR sends YYYYMMDD; render as YYYY-MM-DD. Anything already
 * dashed (or in another shape) passes through unchanged.
 *   "20260321" -> "2026-03-21"
 */
export function formatExpiry(
  value: string | null | undefined,
  fallback = MISSING,
): string {
  if (!value) return fallback;
  if (value.length === 8 && !value.includes("-")) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

/**
 * Calendar date only, in the browser locale.
 *   "2026-03-21T14:30:00Z" -> "3/21/2026" (en-US)
 */
export function formatDate(
  value: string | null | undefined,
  fallback = MISSING,
): string {
  const parsed = parseTime(value);
  if (parsed === null) return fallback;
  return new Date(parsed).toLocaleDateString();
}

/**
 * Date and time, in the browser locale.
 *   "2026-03-21T14:30:00Z" -> "3/21/2026, 2:30:00 PM" (en-US)
 */
export function formatDateTime(
  value: string | null | undefined,
  fallback = MISSING,
): string {
  const parsed = parseTime(value);
  if (parsed === null) return fallback;
  return new Date(parsed).toLocaleString();
}

/**
 * Epoch milliseconds for an ISO timestamp, or null when missing/unparseable.
 */
export function parseTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

/**
 * Elapsed time for queue/run columns. Seconds under a minute, then "Xm Ys",
 * then "Xh Ym". Negative input clamps to 0s.
 *   1500    -> "1s"
 *   95000   -> "1m 35s"
 *   7260000 -> "2h 1m"
 */
export function formatDuration(ms: number | null, fallback = MISSING): string {
  if (ms === null) return fallback;
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}
