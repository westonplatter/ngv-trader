// Privacy-aware wrappers around the number formatters. Each one returns
// PRIVACY_MASK when privacy mode is on and the unmasked formatter's output
// otherwise, so a call site never writes `privacyMode ? PRIVACY_MASK : ...`.
//
// Pure (no React) so it can be tested with `bun test`; `hooks/useFormatters.ts`
// binds it to the privacy context. Components that already receive
// `privacyMode` as a prop call `makeFormatters(privacyMode)` directly.

import { formatGreek, formatMoney, formatPercent } from "./number";
import { PRIVACY_MASK, formatRelativeReturn } from "./privacy";

export interface Formatters {
  /** Money with a mask; `fallback` is what a null value shows when unmasked. */
  money: (value: number | null | undefined, fallback?: string) => string;
  /** Share/contract count, rendered raw when unmasked. */
  quantity: (value: number) => number | string;
  /** Greek (delta/gamma/...) with a mask. */
  greek: (value: number | null | undefined, fallback?: string) => string;
  /** Decimal fraction as a percent with a mask. */
  percent: (value: number | null | undefined, fallback?: string) => string;
  /**
   * P&L: a relative return (P&L / |cost basis|) when masked, so a viewer sees
   * performance without a dollar figure; otherwise `format` (default
   * `formatMoney`) for call sites that show a different money style.
   */
  pnl: (
    value: number | null | undefined,
    costBasis: number | null | undefined,
    format?: (value: number | null) => string,
  ) => string;
  /** Any value that is hidden as-is in privacy mode (ids, raw prices, text). */
  masked: <T>(value: T) => T | string;
}

export function makeFormatters(privacyMode: boolean): Formatters {
  return {
    money: (value, fallback) =>
      privacyMode ? PRIVACY_MASK : formatMoney(value, fallback),
    quantity: (value) => (privacyMode ? PRIVACY_MASK : value),
    greek: (value, fallback) =>
      privacyMode ? PRIVACY_MASK : formatGreek(value, fallback),
    percent: (value, fallback) =>
      privacyMode ? PRIVACY_MASK : formatPercent(value, fallback),
    pnl: (value, costBasis, format = formatMoney) =>
      privacyMode
        ? formatRelativeReturn(value, costBasis)
        : format(value ?? null),
    masked: (value) => (privacyMode ? PRIVACY_MASK : value),
  };
}
