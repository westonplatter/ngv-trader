// The right-hand detail of the selected trade group: header and actions, the
// P&L cards, the account filter, and the positions and trades tables, or the
// edit form. The page mounts it keyed by group id, so the account filter and
// the open edit form reset by remount when another group is selected.

import { useState } from "react";
import { sortGroupPositions } from "../../lib/strategies/groupPositions";
import type { Strategy } from "../../types/strategies";
import type {
  GroupAccountPnl,
  GroupExecutionsResponse,
  TradeGroupDetail,
} from "../../types/tradeGroups";
import GroupDetailHeader from "./GroupDetailHeader";
import GroupEditForm from "./GroupEditForm";
import { GroupAccountBreakdown, GroupPnlSummary } from "./GroupPnlSummary";
import GroupPositionsTable from "./GroupPositionsTable";
import GroupTradesTable from "./GroupTradesTable";
import type { GroupLiveSync } from "./useGroupLiveSync";
import type { GroupPatch } from "./useTradeGroups";

// Splits the tables below by account; only shown with more than one.
function AccountFilter({
  byAccount,
  value,
  onChange,
}: {
  byAccount: GroupAccountPnl[];
  value: number | null;
  onChange: (accountId: number | null) => void;
}) {
  if (byAccount.length <= 1) return null;
  const chip = (
    active: boolean,
    label: string,
    onClick: () => void,
    key: string | number,
  ) => (
    <button
      key={key}
      type="button"
      onClick={onClick}
      className={`rounded-full border px-2.5 py-0.5 text-xs ${
        active
          ? "border-gray-800 bg-gray-800 text-white"
          : "border-gray-300 bg-white text-gray-600 hover:bg-gray-50"
      }`}
    >
      {label}
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-gray-500">Account:</span>
      {chip(value == null, "All", () => onChange(null), "all")}
      {byAccount.map((a) =>
        chip(
          value === a.account_id,
          a.account_alias ?? `Account ${a.account_id}`,
          () => onChange(a.account_id),
          a.account_id,
        ),
      )}
    </div>
  );
}

export default function GroupDetailPane({
  detail,
  executions,
  strategyName,
  strategies,
  focusActive,
  onToggleFocus,
  privacyMode,
  liveSync,
  onTagsChanged,
  onTasksChanged,
  onSave,
  onDelete,
}: {
  detail: TradeGroupDetail;
  // Null until the executions payload has loaded.
  executions: GroupExecutionsResponse | null;
  strategyName: string | null;
  strategies: Strategy[];
  focusActive: boolean;
  onToggleFocus: () => void;
  privacyMode: boolean;
  liveSync: GroupLiveSync;
  onTagsChanged: () => void;
  onTasksChanged: () => void;
  onSave: (body: GroupPatch) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  // Account filter for the Open Positions / Trades tables (null = all accounts).
  const [accountFilter, setAccountFilter] = useState<number | null>(null);

  if (editing) {
    return (
      <GroupEditForm
        detail={detail}
        strategies={strategies}
        onSave={(body) => onSave(body).then(() => setEditing(false))}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const openPositions = executions?.open_positions ?? [];
  const allExecutions = executions?.executions ?? [];
  const visiblePositions = sortGroupPositions(
    accountFilter == null
      ? openPositions
      : openPositions.filter((p) => p.account_id === accountFilter),
  );
  const visibleExecutions =
    accountFilter == null
      ? allExecutions
      : allExecutions.filter((e) => e.account_id === accountFilter);

  return (
    <div className="space-y-4">
      <GroupDetailHeader
        detail={detail}
        strategyName={strategyName}
        focusActive={focusActive}
        onToggleFocus={onToggleFocus}
        onTagsChanged={onTagsChanged}
        onTasksChanged={onTasksChanged}
        onEdit={() => setEditing(true)}
        onDelete={onDelete}
        liveSync={liveSync}
      />

      {executions && (
        <>
          <GroupPnlSummary executions={executions} privacyMode={privacyMode} />
          <GroupAccountBreakdown
            executions={executions}
            privacyMode={privacyMode}
          />
          <AccountFilter
            byAccount={executions.by_account}
            value={accountFilter}
            onChange={setAccountFilter}
          />
        </>
      )}

      <GroupPositionsTable
        positions={visiblePositions}
        totalCount={openPositions.length}
        accountFiltered={accountFilter != null}
        privacyMode={privacyMode}
      />
      <GroupTradesTable
        executions={visibleExecutions}
        totalCount={allExecutions.length}
        accountFiltered={accountFilter != null}
        privacyMode={privacyMode}
      />
    </div>
  );
}
