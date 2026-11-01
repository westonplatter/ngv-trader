// The table itself: sortable columns, one row per trade group, and the empty
// state. It owns the sort; clicking a row opens that group in the workspace.

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useFormatters } from "../../hooks/useFormatters";
import {
  DEFAULT_SORT,
  EMPTY_CELL,
  type SortColumn,
  type SortState,
  ariaSort,
  formatFreshness,
  formatInstruments,
  nextSortState,
  resolvePnl,
  sortIndicator,
  sortRows,
  strategyLabel,
} from "../../lib/strategyPnl";
import type { Account } from "../../types/accounts";
import type { TradeGroupPnlRow } from "../../types/tradeGroups";

const FRESHNESS_CLASS: Record<string, string> = {
  live: "text-emerald-700",
  stale: "text-amber-600",
  none: "text-gray-400",
};

function pnlClass(value: number | null): string {
  if (value == null || value === 0) return "text-gray-700";
  return value > 0 ? "text-emerald-700" : "text-red-600";
}

export default function StrategyPnlGrid({
  rows,
  accounts,
  loading,
  filtersActive,
}: {
  rows: TradeGroupPnlRow[];
  accounts: Account[];
  loading: boolean;
  filtersActive: boolean;
}) {
  const navigate = useNavigate();
  const fmt = useFormatters();
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);

  const header = (
    column: SortColumn,
    label: string,
    align: "left" | "right" = "right",
  ) => (
    <th
      scope="col"
      aria-sort={ariaSort(sort, column)}
      className={`px-3 py-2 font-semibold text-gray-600 text-${align}`}
    >
      <button
        type="button"
        onClick={() => setSort((prev) => nextSortState(prev, column))}
        className="inline-flex items-center gap-1 hover:text-gray-900"
      >
        {label}
        <span className="text-gray-400">{sortIndicator(sort, column)}</span>
      </button>
    </th>
  );

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead className="border-b border-gray-200 bg-gray-50">
          <tr>
            {header("strategy", "Strategy", "left")}
            {header("group", "Group", "left")}
            <th
              scope="col"
              className="px-3 py-2 text-left font-semibold text-gray-600"
            >
              Account
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-left font-semibold text-gray-600"
            >
              Instruments
            </th>
            {header("realized", "Realized")}
            {header("unrealized", "Unrealized")}
            {header("total", "Total")}
            <th
              scope="col"
              className="px-3 py-2 text-left font-semibold text-gray-600"
            >
              Status
            </th>
            <th
              scope="col"
              className="px-3 py-2 text-left font-semibold text-gray-600"
            >
              Marks
            </th>
          </tr>
        </thead>
        <tbody>
          {!loading && sorted.length === 0 && (
            <tr>
              <td
                colSpan={9}
                className="px-3 py-6 text-center text-sm text-gray-500"
              >
                {filtersActive
                  ? "No trade groups match these filters."
                  : "No trade groups yet."}
              </td>
            </tr>
          )}
          {sorted.map((group) => {
            const pnl = resolvePnl(group);
            const freshness = formatFreshness(
              group.marks_as_of,
              group.live_is_stale,
            );
            const account = accounts.find((a) => a.id === group.account_id);
            return (
              <tr
                key={group.id}
                // The workspace reads `trade_group_id` from the query string and opens
                // that group's detail panel.
                onClick={() =>
                  navigate(`/strategies?trade_group_id=${group.id}`)
                }
                className="cursor-pointer border-b border-gray-100 hover:bg-gray-50"
              >
                <td className="px-3 py-2 text-gray-700">
                  {strategyLabel(group)}
                </td>
                <td className="px-3 py-2 font-medium text-gray-900">
                  {group.name}
                </td>
                <td className="px-3 py-2 text-gray-600">
                  {account?.alias ?? account?.masked_account ?? EMPTY_CELL}
                </td>
                <td className="px-3 py-2 text-gray-600">
                  {formatInstruments(group.instruments)}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums ${pnlClass(pnl.realized)}`}
                >
                  {fmt.money(pnl.realized)}
                </td>
                <td
                  className={`px-3 py-2 text-right tabular-nums ${pnlClass(pnl.unrealized)}`}
                >
                  {fmt.money(pnl.unrealized)}
                </td>
                <td
                  className={`px-3 py-2 text-right font-semibold tabular-nums ${pnlClass(pnl.total)}`}
                >
                  {fmt.money(pnl.total)}
                </td>
                <td className="px-3 py-2 text-gray-600">{group.status}</td>
                <td
                  className={`px-3 py-2 text-xs ${FRESHNESS_CLASS[freshness.tone]}`}
                  title={freshness.title}
                >
                  {freshness.label}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
