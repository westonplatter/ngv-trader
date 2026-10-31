// Pure math behind a trade group's detail: position greeks in underlying
// units, the open-positions ordering and totals, capital invested, the
// per-account split, and the running realized P&L of the trades table.
//
// Kept out of the components so the behavior has a bun test: the repo has no
// DOM harness, so anything worth asserting must be a function over plain data.

import type {
  GroupAccountPnl,
  GroupExecution,
  GroupOpenPosition,
} from "../../types/tradeGroups";

// Contract multipliers that arrive as strings on the positions payload. Mirrors
// the backend's ``parse_multiplier``: missing/unparseable falls back to 1.
export function parseMultiplier(value: string | null | undefined): number {
  if (value == null || value === "") return 1;
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? num : 1;
}

// Futures and stock carry no option metrics, but their delta is definitionally
// 1.0 per unit (gamma 0), so they are folded in rather than dropped from the total.
const DELTA_ONE_SEC_TYPES = new Set(["FUT", "CONTFUT", "FUTURE", "STK"]);

/**
 * Position greeks in underlying units (barrels, shares, …): per-unit greek ×
 * signed qty × the contract multiplier off the positions snapshot. Weighting
 * matters because a group can mix contract sizes — a short MCL (100) is −100
 * bbl and a short CL (1000) is −1000 bbl, so they must not add as equals.
 * Option greeks are live-sourced, so they blank out when the live overlay is
 * stale; the futures/stock delta is a constant and always counts.
 */
export function positionGreeks(pos: GroupOpenPosition): {
  delta: number | null;
  gamma: number | null;
} {
  const multiplier = parseMultiplier(pos.multiplier);
  if (DELTA_ONE_SEC_TYPES.has((pos.sec_type ?? "").toUpperCase())) {
    return { delta: pos.position * multiplier, gamma: 0 };
  }
  if (pos.live_is_stale) return { delta: null, gamma: null };
  return {
    delta: pos.delta == null ? null : pos.delta * pos.position * multiplier,
    gamma: pos.gamma == null ? null : pos.gamma * pos.position * multiplier,
  };
}

export function positionAccountLabel(p: GroupOpenPosition): string {
  return p.account_alias ?? `Account ${p.account_id}`;
}

export function positionContractLabel(p: GroupOpenPosition): string {
  return p.contract_display ?? p.local_symbol ?? p.symbol ?? `#${p.con_id}`;
}

// Option strike parsed from the display (e.g. "CL 70.5 CALL" -> 70.5), used to
// order strikes numerically instead of lexically. Null for non-options.
export function positionStrike(p: GroupOpenPosition): number | null {
  const m = /(-?\d+(?:\.\d+)?)\s+(?:CALL|PUT)/i.exec(p.contract_display ?? "");
  return m ? Number.parseFloat(m[1]) : null;
}

// Account, then symbol, then strike (high -> low), then natural-numeric
// fallback on the display for anything without a strike (e.g. futures).
export function sortGroupPositions(
  positions: GroupOpenPosition[],
): GroupOpenPosition[] {
  return positions.slice().sort((a, b) => {
    const acct = positionAccountLabel(a).localeCompare(positionAccountLabel(b));
    if (acct !== 0) return acct;
    const sym = (a.symbol ?? "").localeCompare(b.symbol ?? "");
    if (sym !== 0) return sym;
    const sa = positionStrike(a);
    const sb = positionStrike(b);
    if (sa != null && sb != null && sa !== sb) return sb - sa;
    return positionContractLabel(a).localeCompare(
      positionContractLabel(b),
      undefined,
      { numeric: true },
    );
  });
}

// Google-Sheets-style banding: each account group gets a subtle alternating
// background so rows read as grouped by account. 0 or 1 per account id, in
// the order the accounts first appear.
export function accountBands(positions: GroupOpenPosition[]): Map<number, number> {
  const bands = new Map<number, number>();
  for (const p of positions) {
    if (!bands.has(p.account_id)) bands.set(p.account_id, bands.size % 2);
  }
  return bands;
}

export interface SumCount {
  sum: number;
  count: number;
}

export interface GroupPositionTotals {
  delta: SumCount;
  gamma: SumCount;
  avgCost: SumCount;
  costBasis: SumCount;
  value: SumCount;
  unrealized: SumCount;
  liveUnrealized: SumCount;
}

// Aggregate row for the Open Positions table: sums follow the same staleness
// rule as the per-row cells — delta/gamma/live_unrealized are excluded for a
// stale live overlay, while the settled fields (avg_cost, position_value,
// fifo_pnl_unrealized) are summed regardless of staleness.
export function positionTotals(
  positions: GroupOpenPosition[],
): GroupPositionTotals {
  return positions.reduce<GroupPositionTotals>(
    (acc, pos) => {
      const liveStale = pos.live_is_stale;
      const greeks = positionGreeks(pos);
      if (greeks.delta != null) {
        acc.delta.sum += greeks.delta;
        acc.delta.count += 1;
      }
      if (greeks.gamma != null) {
        acc.gamma.sum += greeks.gamma;
        acc.gamma.count += 1;
      }
      // avg_cost is stored as a positive magnitude (entry price × multiplier ×
      // |qty|); apply the position's sign so a short contributes a credit.
      acc.avgCost.sum += pos.avg_cost * Math.sign(pos.position);
      acc.avgCost.count += 1;
      // Cost basis is multiplier-inclusive avg_cost × signed quantity, so long
      // legs read as a debit and short legs as a credit; the total nets out to
      // the spread's net debit/credit.
      acc.costBasis.sum += pos.avg_cost * pos.position;
      acc.costBasis.count += 1;
      if (pos.position_value != null) {
        acc.value.sum += pos.position_value;
        acc.value.count += 1;
      }
      if (pos.fifo_pnl_unrealized != null) {
        acc.unrealized.sum += pos.fifo_pnl_unrealized;
        acc.unrealized.count += 1;
      }
      if (!liveStale && pos.live_unrealized != null) {
        acc.liveUnrealized.sum += pos.live_unrealized;
        acc.liveUnrealized.count += 1;
      }
      return acc;
    },
    {
      delta: { sum: 0, count: 0 },
      gamma: { sum: 0, count: 0 },
      avgCost: { sum: 0, count: 0 },
      costBasis: { sum: 0, count: 0 },
      value: { sum: 0, count: 0 },
      unrealized: { sum: 0, count: 0 },
      liveUnrealized: { sum: 0, count: 0 },
    },
  );
}

export interface GroupCapital {
  capital: number | null;
  optionsCapital: number | null;
  equityCapital: number | null;
}

function isOption(pos: GroupOpenPosition): boolean {
  return pos.sec_type === "OPT" || pos.sec_type === "FOP";
}

// Capital invested in the group. IBKR avg_cost is already multiplier-inclusive
// (per-contract for options/futures, per-share for stocks), so a leg's cost
// basis is avg_cost * position. Accumulate the SIGNED basis so long and short
// legs of a spread net out — a calendar/vertical spread's real capital is the
// net debit, not the gross notional of both legs (which over-counts ~2x+ for
// offsetting legs). Then report the magnitude per bucket: a net debit (capital
// outlaid) and a net credit (premium received) both represent capital
// committed. All null when there are no positions or both buckets net to zero.
export function groupCapital(openPositions: GroupOpenPosition[]): GroupCapital {
  if (openPositions.length === 0) {
    return { capital: null, optionsCapital: null, equityCapital: null };
  }
  let optionsSum = 0;
  let equitySum = 0;
  for (const pos of openPositions) {
    const posBasis = pos.avg_cost * pos.position;
    if (isOption(pos)) optionsSum += posBasis;
    else equitySum += posBasis;
  }
  const optionsAbs = Math.abs(optionsSum);
  const equityAbs = Math.abs(equitySum);
  if (optionsAbs + equityAbs > 0) {
    return {
      capital: optionsAbs + equityAbs,
      optionsCapital: optionsAbs,
      equityCapital: equityAbs,
    };
  }
  return { capital: null, optionsCapital: null, equityCapital: null };
}

// Per-account capital: net signed cost basis per bucket, then magnitude — the
// same convention as groupCapital so spread legs net out rather than
// double-counting. Null when the account holds nothing in the group.
export function capitalForAccount(
  openPositions: GroupOpenPosition[],
  accountId: number,
): number | null {
  let optionsSum = 0;
  let equitySum = 0;
  let any = false;
  for (const pos of openPositions) {
    if (pos.account_id !== accountId) continue;
    any = true;
    const basis = pos.avg_cost * pos.position;
    if (isOption(pos)) optionsSum += basis;
    else equitySum += basis;
  }
  if (!any) return null;
  return Math.abs(optionsSum) + Math.abs(equitySum);
}

// Realized + unrealized, or null when neither is known.
export function totalPnl(
  unrealized: number | null,
  realized: number | null,
): number | null {
  if (unrealized == null && realized == null) return null;
  return (unrealized ?? 0) + (realized ?? 0);
}

export function accountTotal(acct: GroupAccountPnl): number | null {
  return totalPnl(acct.unrealized_pnl, acct.realized_pnl);
}

// By total P&L (realized + unrealized) descending; accounts with no P&L data
// sort last.
export function sortAccountPnl(byAccount: GroupAccountPnl[]): GroupAccountPnl[] {
  const totalOf = (x: GroupAccountPnl) => accountTotal(x) ?? -Infinity;
  return [...byAccount].sort((a, b) => totalOf(b) - totalOf(a));
}

// True when any open position has a usable live mark, which decides whether the
// intraday block reads "live as of" or "stale as of".
export function hasFreshLive(openPositions: GroupOpenPosition[]): boolean {
  return openPositions.some((p) => p.source === "live" && !p.live_is_stale);
}

export interface ExecutionWithRunning {
  ex: GroupExecution;
  // Whether this row contributes to the running total: realized P&L is
  // present and the row is not a combo summary (legs already carry it).
  counted: boolean;
  running: number;
}

// Running realized P&L in the order given (oldest first). The table renders
// the result reversed so the newest trade sits at the top with the group's
// cumulative figure.
export function runningRealized(
  executions: GroupExecution[],
): ExecutionWithRunning[] {
  let running = 0;
  return executions.map((ex) => {
    const counted = ex.realized_pnl != null && ex.exec_role !== "combo_summary";
    if (counted) running += ex.realized_pnl as number;
    return { ex, counted, running };
  });
}
