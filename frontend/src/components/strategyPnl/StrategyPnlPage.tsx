// Strategy P&L — one row per trade group, with its strategy and P&L split.
//
// Sibling to the three-column Strategies workspace (`StrategiesPage`), which
// answers "how is this group doing"; this answers "how is the book doing".
// Read-only by design: assignment, renaming, and status changes stay on the
// workspace page.
//
// All the logic worth asserting lives in ../../lib/strategyPnl so it can be
// tested without a DOM. This file only wires the hooks to the panes.

import StrategyPnlGrid from "./StrategyPnlGrid";
import StrategyPnlToolbar from "./StrategyPnlToolbar";
import { useIntradayRefresh } from "./useIntradayRefresh";
import { useStrategyPnlRows } from "./useStrategyPnlRows";

export default function StrategyPnlPage() {
  const data = useStrategyPnlRows();
  const refresh = useIntradayRefresh(data.reload);

  return (
    <div className="space-y-3">
      <StrategyPnlToolbar data={data} refresh={refresh} />

      {refresh.message && (
        <p className="text-xs text-emerald-700">{refresh.message}</p>
      )}
      {data.error && (
        <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {data.error}
        </p>
      )}

      <StrategyPnlGrid
        rows={data.rows}
        accounts={data.accounts}
        loading={data.loading}
        filtersActive={data.filtersActive}
      />
    </div>
  );
}
