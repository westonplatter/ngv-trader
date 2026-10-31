// /positions: the settled FlexQuery snapshot with the live TWS overlay, trade
// group assignment, tags, and tasks per row. This file only wires the hooks to
// the panes; the data lives in usePositions, the view state in
// usePositionView, the manual syncs in usePositionSync.

import { usePrivacy } from "../../contexts/usePrivacy";
import PositionsTableBody from "./PositionsTableBody";
import PositionsToolbar from "./PositionsToolbar";
import { usePositions } from "./usePositions";
import { usePositionSync } from "./usePositionSync";
import { usePositionView } from "./usePositionView";

export default function PositionsPage() {
  const { privacyMode } = usePrivacy();
  const data = usePositions();
  const sync = usePositionSync(data.reload);
  const view = usePositionView(data.positions);

  if (data.loading) return <p className="text-gray-500">Loading positions...</p>;
  if (data.error) return <p className="text-red-600">Error: {data.error}</p>;
  if (data.positions.length === 0)
    return <p className="text-gray-500">No positions found.</p>;

  return (
    <div className="space-y-3">
      <PositionsToolbar
        totals={view.totals}
        privacyMode={privacyMode}
        sync={sync}
        showGreeks={view.showGreeks}
        onToggleGreeks={view.toggleGreeks}
        onClearFilters={view.clearFilters}
        accountAliases={view.accountAliases}
        accountFilter={view.filters.account}
        onAccountFilter={(alias) => view.setFilter("account", alias)}
        assignError={data.assignError}
      />
      <PositionsTableBody
        columns={view.columns}
        rows={view.rows}
        filters={view.filters}
        onFilter={view.setFilter}
        sort={view.sort}
        onToggleSort={view.toggleSort}
        privacyMode={privacyMode}
        onAssign={data.assignToTradeGroup}
        onUnassign={data.unassignFromTradeGroup}
        onChanged={data.reload}
      />
    </div>
  );
}
