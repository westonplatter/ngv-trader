// The executions table: header with the select-all box and the Contract
// filter, then one TradeRow per filtered execution. Row and symbol highlight
// is view state local to the table.

import { useState } from "react";
import { rowGroupId, rowGroupKey, rowSymbol } from "../../lib/trades/view";
import type { TradeExecutionRow } from "../../types/trades";
import TradeRow from "./TradeRow";
import type { BulkTagging } from "./useBulkTagging";

const TH = "whitespace-nowrap px-3 py-2 font-semibold text-gray-700";

export default function TradesTableBody({
  rows,
  owners,
  groupLabelById,
  showDetails,
  symbolFilter,
  onSymbolFilter,
  privacyMode,
  loading,
  bulk,
  onAssigned,
  onChanged,
}: {
  rows: TradeExecutionRow[];
  owners: Map<string, number>;
  groupLabelById: Map<number, string>;
  showDetails: boolean;
  symbolFilter: string;
  onSymbolFilter: (value: string) => void;
  privacyMode: boolean;
  loading: boolean;
  bulk: BulkTagging;
  onAssigned: () => void;
  onChanged: () => void;
}) {
  const [highlightedGroupKey, setHighlightedGroupKey] = useState<
    string | null
  >(null);
  const [highlightedSymbol, setHighlightedSymbol] = useState<string | null>(
    null,
  );

  const toggleHighlight = (groupKey: string) => {
    setHighlightedGroupKey((current) =>
      current === groupKey ? null : groupKey,
    );
  };
  const toggleSymbolHighlight = (symbol: string | null) => {
    if (!symbol || symbol === "-") return;
    setHighlightedSymbol((current) => (current === symbol ? null : symbol));
  };

  return (
    <div className="overflow-x-auto rounded border border-gray-200 bg-white">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            <th className="w-6 px-2 py-2">
              <input
                type="checkbox"
                aria-label="Select all visible orders"
                checked={bulk.allSelected}
                onChange={(event) => bulk.selectAll(event.target.checked)}
              />
            </th>
            <th className={TH}>Account</th>
            <th className={TH}>Time</th>
            <th className={TH}>
              <div className="space-y-1">
                <input
                  value={symbolFilter}
                  onChange={(event) => onSymbolFilter(event.target.value)}
                  placeholder="Filter"
                  className="w-24 rounded border border-gray-300 px-2 py-0.5 text-xs font-normal text-gray-700"
                />
                <div>Contract</div>
              </div>
            </th>
            <th className="w-12 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
              Role
            </th>
            <th className="w-16 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
              Action
            </th>
            <th className="w-8 whitespace-nowrap px-1 py-2 font-semibold text-gray-700">
              Type
            </th>
            <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
              Side
            </th>
            <th className="w-10 whitespace-nowrap px-2 py-2 font-semibold text-gray-700">
              Qty
            </th>
            <th className={TH}>Price</th>
            <th className={TH}>Realized PnL</th>
            <th className={TH}>Status</th>
            <th className={TH}>Codes</th>
            <th className="w-48 min-w-[12rem] whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
              Trade Group
            </th>
            <th className="min-w-[10rem] whitespace-nowrap px-3 py-2 font-semibold text-gray-700">
              Tags
            </th>
            <th className={TH}>Tasks</th>
            <th className={TH}>Parent Exec ID</th>
            <th className={TH}>Order Ref</th>
            {showDetails && (
              <>
                <th className={TH}>Exec ID</th>
                <th className={TH}>Con ID</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={19} className="px-3 py-6 text-center text-gray-500">
                No executions found.
              </td>
            </tr>
          )}
          {rows.map((row) => {
            const groupKey = rowGroupKey(row);
            const groupId = rowGroupId(row);
            const symbol = rowSymbol(row);
            return (
              <TradeRow
                key={row.id}
                row={row}
                ownsGroupCell={owners.get(groupKey) === row.id}
                groupLabel={
                  groupId !== null ? (groupLabelById.get(groupId) ?? null) : null
                }
                showDetails={showDetails}
                privacyMode={privacyMode}
                selected={bulk.selectedKeys.has(groupKey)}
                isHighlighted={highlightedGroupKey === groupKey}
                isSymbolHighlighted={
                  highlightedSymbol !== null && symbol === highlightedSymbol
                }
                onToggleSelected={bulk.toggle}
                onToggleHighlight={toggleHighlight}
                onToggleSymbolHighlight={toggleSymbolHighlight}
                onAssigned={onAssigned}
                onChanged={onChanged}
              />
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
