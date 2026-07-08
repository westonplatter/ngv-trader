// Shared finance-style number formatters for the data tables.
//
// The goal is consistent, readable numbers across Positions and Trades:
// money-like columns always show exactly 2 decimals with thousands separators,
// while strikes/multipliers use thousands separators without forced trailing
// zeros. Identifiers (con_id, exec ids) are intentionally NOT routed through
// these helpers so they never gain commas.

/**
 * Money / price / PnL / value / cost.
 * Always exactly 2 decimals with thousands separators.
 *   21850   -> "21,850.00"
 *   1320615 -> "1,320,615.00"
 *   117.5   -> "117.50"
 */
export function formatMoney(
  value: number | null | undefined,
  fallback = "—",
): string {
  if (value == null) return fallback;
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Strike. Thousands separators, up to 2 decimals, no forced trailing zeros.
 *   6000 -> "6,000"
 *   311  -> "311"
 */
export function formatStrike(
  value: number | null | undefined,
  fallback = "—",
): string {
  if (value == null) return fallback;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/**
 * Implied volatility. A decimal fraction rendered as a percent.
 *   0.2453 -> "24.5%"
 */
export function formatPercent(
  value: number | null | undefined,
  fallback = "—",
): string {
  if (value == null) return fallback;
  return `${(value * 100).toLocaleString(undefined, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}%`;
}

/**
 * Greek (delta/gamma/theta/vega). Signed, up to 3 decimals, no thousands sep.
 *   0.4231  -> "0.423"
 *   -0.05   -> "-0.05"
 */
export function formatGreek(
  value: number | null | undefined,
  fallback = "—",
): string {
  if (value == null) return fallback;
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

/**
 * Multiplier. Thousands separators, integer.
 *   1000 -> "1,000"
 * Accepts strings (the positions payload types multiplier as a string).
 */
export function formatMultiplier(
  value: number | string | null | undefined,
  fallback = "—",
): string {
  if (value == null || value === "") return fallback;
  const num = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(num)) return String(value);
  return num.toLocaleString(undefined, { maximumFractionDigits: 0 });
}
