// The Trades table of a group's detail, newest first, with a running realized
// P&L column. Rows are already account-filtered.

import { ibCodesTitle, parseIbCodes } from "../../lib/ibCodes";
import { runningRealized } from "../../lib/strategies/groupPositions";
import type { GroupExecution } from "../../types/tradeGroups";
import { formatDateTime } from "../../utils/date";
import { formatMoney } from "../../utils/number";
import { PRIVACY_MASK } from "../../utils/privacy";

const TH_RIGHT = "px-2 py-1 text-right font-medium";

function CodesCell({ codes }: { codes: string | null }) {
  if (!codes) return <span className="text-gray-400">—</span>;
  return (
    <span className="group/codes relative inline-block">
      <span
        className="cursor-default rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] font-medium text-slate-700"
        title={ibCodesTitle(codes)}
      >
        {codes}
      </span>
      <span className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-max max-w-xs rounded bg-gray-900 px-2 py-1 text-[11px] text-white shadow-lg group-hover/codes:block">
        {parseIbCodes(codes).map(({ code, label }) => (
          <span key={code} className="block">
            <span className="font-mono font-semibold">{code}</span> — {label}
          </span>
        ))}
      </span>
    </span>
  );
}

export default function GroupTradesTable({
  executions,
  totalCount,
  accountFiltered,
  privacyMode,
}: {
  // Visible (account-filtered) executions, oldest first as the API sends them.
  executions: GroupExecution[];
  totalCount: number;
  accountFiltered: boolean;
  privacyMode: boolean;
}) {
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
          Trades ({executions.length}
          {accountFiltered ? ` of ${totalCount}` : ""})
        </h5>
      </div>
      {executions.length === 0 && (
        <p className="mb-3 text-xs text-gray-400">
          No trades assigned to this group yet.
        </p>
      )}
      {executions.length > 0 && (
        <div className="mb-4 max-h-[300px] overflow-auto rounded border border-gray-200">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-gray-50 text-gray-600">
              <tr>
                <th className="px-2 py-1 font-medium">When</th>
                <th className="px-2 py-1 font-medium">Account</th>
                <th className="px-2 py-1 font-medium">Contract</th>
                <th className="px-2 py-1 font-medium">Codes</th>
                <th className={TH_RIGHT}>Side</th>
                <th className={TH_RIGHT}>Qty</th>
                <th className={TH_RIGHT}>Price</th>
                <th
                  className={TH_RIGHT}
                  title="Signed qty × price × contract multiplier + commission. Positive = debit paid, negative = credit received. Combo summary rows show — so legs aren't double-counted."
                >
                  Cost Basis
                </th>
                <th className={TH_RIGHT}>Realized</th>
                <th className={TH_RIGHT}>Cum PnL</th>
              </tr>
            </thead>
            <tbody>
              {[...runningRealized(executions)]
                .reverse()
                .map(({ ex, counted, running }) => {
                  const sideClass =
                    ex.side && /^(BOT|BUY)$/i.test(ex.side)
                      ? "text-emerald-700"
                      : ex.side
                        ? "text-red-700"
                        : "text-gray-500";
                  const pnlClass =
                    ex.realized_pnl == null
                      ? "text-gray-400"
                      : ex.realized_pnl >= 0
                        ? "text-emerald-700"
                        : "text-red-700";
                  return (
                    <tr key={ex.id} className="border-t border-gray-100">
                      <td className="px-2 py-1 text-gray-700">
                        {formatDateTime(ex.executed_at)}
                      </td>
                      <td className="px-2 py-1 text-gray-700">
                        {ex.account_alias ?? `Account ${ex.account_id}`}
                      </td>
                      <td className="px-2 py-1 text-gray-800">
                        {ex.contract_display ??
                          (ex.trade_id != null ? `#${ex.trade_id}` : "—")}
                        {ex.exec_role !== "standalone" && (
                          <span className="ml-1 rounded bg-gray-100 px-1 py-0.5 text-[10px] uppercase text-gray-500">
                            {ex.exec_role}
                          </span>
                        )}
                        {ex.settled === false && (
                          <span className="ml-1 rounded bg-amber-100 px-1 py-0.5 text-[10px] uppercase text-amber-800">
                            unsettled
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1">
                        <CodesCell codes={ex.ib_codes} />
                      </td>
                      <td className={`px-2 py-1 text-right font-mono ${sideClass}`}>
                        {ex.side ?? "—"}
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-gray-800">
                        {privacyMode ? PRIVACY_MASK : ex.quantity}
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-gray-800">
                        {privacyMode ? PRIVACY_MASK : Number(ex.price.toFixed(4))}
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-gray-800">
                        {privacyMode
                          ? PRIVACY_MASK
                          : ex.cost_basis == null
                            ? "—"
                            : formatMoney(ex.cost_basis)}
                      </td>
                      <td className={`px-2 py-1 text-right font-mono ${pnlClass}`}>
                        {privacyMode
                          ? PRIVACY_MASK
                          : ex.realized_pnl == null
                            ? "—"
                            : ex.realized_pnl.toFixed(2)}
                      </td>
                      <td className="px-2 py-1 text-right font-mono text-gray-700">
                        {privacyMode ? PRIVACY_MASK : counted ? running.toFixed(2) : "—"}
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
