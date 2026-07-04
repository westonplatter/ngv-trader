export const PRIVACY_MASK = "•••";

/**
 * Privacy-mode P&L formatter: render a gain/loss as a relative return
 * percentage (P&L ÷ |cost basis|) instead of an absolute dollar figure.
 *
 * Lets a viewer see how a position/strategy performed without exposing any
 * dollar amount. Falls back to PRIVACY_MASK when inputs are missing or the
 * cost basis is ~0 (percentage would be undefined/meaningless).
 *
 *   formatRelativeReturn(1250, 10000) -> "+12.5%"
 *   formatRelativeReturn(-300, 6000)  -> "-5.0%"
 */
export function formatRelativeReturn(
  pnl: number | null | undefined,
  costBasis: number | null | undefined,
): string {
  if (pnl == null || costBasis == null) return PRIVACY_MASK;
  const denom = Math.abs(costBasis);
  if (!Number.isFinite(denom) || denom < 1e-9) return PRIVACY_MASK;
  const pct = (pnl / denom) * 100;
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(1)}%`;
}
