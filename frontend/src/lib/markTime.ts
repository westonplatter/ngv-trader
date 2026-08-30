/**
 * Freshness-timestamp formatting for the live TWS overlay badges.
 *
 * Time-only for a timestamp from today, date-qualified for anything older.
 *
 * The overlay is refreshed by hand, so a snapshot routinely survives days --
 * over a weekend it always does, since there is nothing to reconnect to until
 * the next session. A bare "11:09 PM" on a four-day-old capture reads as
 * tonight, which made the badge least legible exactly when staleness mattered
 * most. Qualifying by date only when the day differs keeps the common green
 * "live as of 11:09 PM" case unchanged (a live mark is from today by
 * definition) while the amber stale case says how far back it actually goes.
 */

function isSameLocalDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/**
 * Render an ISO timestamp for a freshness badge.
 *
 * Returns "" for null/undefined/unparseable input so callers can omit the
 * suffix entirely rather than printing a stray separator.
 */
export function formatMarkTime(value: string | null | undefined): string {
  if (!value) return "";
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "";

  const at = new Date(parsed);
  const time = at.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  if (isSameLocalDay(at, new Date())) return time;

  const day = at.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  return `${day}, ${time}`;
}
