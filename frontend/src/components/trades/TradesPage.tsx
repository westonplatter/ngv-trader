// /trades: settled FlexQuery executions and unsettled TWS fills, with trade
// group assignment, tags, tasks, and bulk tagging per order. This file only
// wires the hooks to the panes; filters are URL state in useTradeFilters, the
// snapshot is useTradeExecutions, the manual syncs are useTradeSync.

import { useMemo } from "react";
import { usePrivacy } from "../../contexts/usePrivacy";
import {
  accountOptions,
  filterExecutions,
  groupCellOwners,
  serverSymbol,
} from "../../lib/trades/view";
import BulkTagBar from "./BulkTagBar";
import TradesFilterBar from "./TradesFilterBar";
import TradesSyncControls from "./TradesSyncControls";
import TradesTableBody from "./TradesTableBody";
import { useBulkTagging } from "./useBulkTagging";
import { useTradeExecutions } from "./useTradeExecutions";
import { useTradeFilters } from "./useTradeFilters";
import { useTradeSync } from "./useTradeSync";

export default function TradesPage() {
  const { privacyMode } = usePrivacy();
  const filterState = useTradeFilters();
  const { filters, conId } = filterState;
  const data = useTradeExecutions({
    serverSymbol: serverSymbol(filters.symbol),
    conId,
  });
  const sync = useTradeSync(data.reloadAll);

  const accounts = useMemo(
    () => accountOptions(data.executions),
    [data.executions],
  );
  const rows = useMemo(
    () => filterExecutions(data.executions, filters, data.filterNow),
    [data.executions, filters, data.filterNow],
  );
  const owners = useMemo(() => groupCellOwners(rows), [rows]);
  const bulk = useBulkTagging(rows, owners, data.refreshQuietly);

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Trades</h2>
          <p className="text-xs text-gray-500">{rows.length} execution(s)</p>
        </div>
        <TradesSyncControls sync={sync} />
      </div>

      <TradesFilterBar
        accounts={accounts}
        state={filterState}
        onTimeRange={(id) => {
          // Re-read the clock so the relative window is measured from now.
          data.markNow();
          filterState.setTimeRange(id);
        }}
      />
      <BulkTagBar bulk={bulk} />

      {data.loading && <p className="text-gray-500">Loading executions...</p>}
      {data.error && <p className="text-red-600">Error: {data.error}</p>}

      <TradesTableBody
        rows={rows}
        owners={owners}
        groupLabelById={data.groupLabelById}
        showDetails={filterState.showDetails}
        symbolFilter={filters.symbol}
        onSymbolFilter={filterState.setSymbol}
        privacyMode={privacyMode}
        loading={data.loading}
        bulk={bulk}
        onAssigned={data.reloadAll}
        onChanged={data.refreshQuietly}
      />
    </div>
  );
}
