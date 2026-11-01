// The P&L card of a group's detail: capital invested by bucket, settled
// totals with percent of capital, and the intraday (live) block with its
// freshness note. Followed by the per-account breakdown when the group spans
// more than one account.

import { formatMarkTime } from "../../lib/markTime";
import {
  accountTotal,
  capitalForAccount,
  groupCapital,
  hasFreshLive,
  sortAccountPnl,
  totalPnl,
} from "../../lib/strategies/groupPositions";
import type { GroupExecutionsResponse } from "../../types/tradeGroups";
import { makeFormatters } from "../../utils/maskedFormatters";
import { formatUsd, pnlClassName } from "./statusStyles";

export function GroupPnlSummary({
  executions,
  privacyMode,
}: {
  executions: GroupExecutionsResponse;
  privacyMode: boolean;
}) {
  const openPositions = executions.open_positions;
  const total = totalPnl(
    executions.total_unrealized_pnl,
    executions.total_realized_pnl,
  );
  const { capital, optionsCapital, equityCapital } =
    groupCapital(openPositions);
  const fmt = makeFormatters(privacyMode);
  const usd = (v: number | null) => fmt.masked(formatUsd(v));
  const pct = (v: number | null) =>
    v == null || capital == null ? "—" : `${((v / capital) * 100).toFixed(2)}%`;
  const row = (
    label: string,
    v: number | null,
    showPct: boolean,
    colorize: boolean,
  ) => (
    <div className="grid grid-cols-[7rem_6rem_5rem] items-baseline">
      <span className="text-gray-500">{label}:</span>
      <span
        className={`text-right ${colorize ? pnlClassName(v) : "font-semibold text-gray-800"}`}
      >
        {usd(v)}
      </span>
      <span
        className={`text-right ${showPct ? pnlClassName(v) : "text-gray-400"}`}
      >
        {showPct ? pct(v) : ""}
      </span>
    </div>
  );
  const subRow = (label: string, v: number | null) => (
    <div className="grid grid-cols-[7rem_6rem_5rem] items-baseline">
      <span className="pl-3 text-gray-400">{label}:</span>
      <span className="text-right font-medium text-gray-600">{usd(v)}</span>
      <span />
    </div>
  );
  const marksAsOf = executions.marks_as_of;
  return (
    <div className="flex flex-col gap-0.5 rounded border border-gray-200 bg-gray-50 px-3 py-1.5 text-xs">
      {row("Capital invested", capital, false, false)}
      {subRow("Options capital", optionsCapital)}
      {subRow("Equity capital", equityCapital)}
      {row("Total PnL", total, true, true)}
      {row("Unrealized PnL", executions.total_unrealized_pnl, true, true)}
      {row("Realized PnL", executions.total_realized_pnl, true, true)}
      <div className="my-1 border-t border-gray-200" />
      <div className="flex items-baseline justify-between">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
          Intraday (live)
        </span>
        <span className="text-[11px] text-gray-400">
          {marksAsOf
            ? hasFreshLive(openPositions)
              ? `live as of ${formatMarkTime(marksAsOf)}`
              : `stale as of ${formatMarkTime(marksAsOf)}`
            : "settled — no live data"}
        </span>
      </div>
      {row("Total PnL", executions.intraday_total_pnl, true, true)}
      {row("Unrealized PnL", executions.intraday_unrealized_pnl, true, true)}
      {row("Realized PnL", executions.intraday_realized_pnl, true, true)}
    </div>
  );
}

// Only meaningful with more than one account.
export function GroupAccountBreakdown({
  executions,
  privacyMode,
}: {
  executions: GroupExecutionsResponse;
  privacyMode: boolean;
}) {
  const { by_account: byAccount, open_positions: openPositions } = executions;
  if (byAccount.length <= 1) return null;
  const fmt = makeFormatters(privacyMode);
  const gridCols =
    "grid grid-cols-[6rem_1fr_1fr_1fr_1fr] items-baseline gap-x-2";
  return (
    <div className="flex flex-col gap-1 rounded border border-gray-200 bg-white px-3 py-2 text-xs">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        By account
      </div>
      <div
        className={`${gridCols} border-b border-gray-100 pb-1 text-[11px] font-medium uppercase tracking-wide text-gray-400`}
      >
        <span>Account</span>
        <span className="text-right">Capital</span>
        <span className="text-right">Total</span>
        <span className="text-right">Realized</span>
        <span className="text-right">Unrealized</span>
      </div>
      {sortAccountPnl(byAccount).map((acct) => {
        const total = accountTotal(acct);
        const capital = capitalForAccount(openPositions, acct.account_id);
        return (
          <div key={acct.account_id} className={gridCols}>
            <span className="font-medium text-gray-700">
              {acct.account_alias ?? acct.account_id}
            </span>
            <span className="text-right text-gray-500">
              {fmt.masked(formatUsd(capital))}
            </span>
            <span className={`text-right ${pnlClassName(total)}`}>
              {fmt.pnl(total, capital, formatUsd)}
            </span>
            <span className={`text-right ${pnlClassName(acct.realized_pnl)}`}>
              {fmt.pnl(acct.realized_pnl, capital, formatUsd)}
            </span>
            <span
              className={`text-right ${pnlClassName(acct.unrealized_pnl)}`}
            >
              {fmt.pnl(acct.unrealized_pnl, capital, formatUsd)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
