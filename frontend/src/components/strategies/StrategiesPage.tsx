// /strategies: the three-column workspace — strategies, their trade groups,
// and the selected group's detail. This file wires the hooks to the panes:
// selection and URL sync in useWorkspaceSelection, the lists and their writes
// in useStrategies and useTradeGroups, the detail in useTradeGroupDetail,
// focus mode in useFocusMode.

import type { CSSProperties } from "react";
import { useCallback, useMemo, useState } from "react";
import { usePrivacy } from "../../contexts/usePrivacy";
import { useResizableColumn } from "../../hooks/useResizableColumn";
import { errorMessage } from "../../lib/api";
import {
  groupSections,
  resolveSelection,
  type GroupFilter,
  type GroupSort,
} from "../../lib/strategies/groups";
import GroupDetailPane from "./GroupDetailPane";
import GroupListPane from "./GroupListPane";
import StrategyListPane from "./StrategyListPane";
import { useFocusMode } from "./useFocusMode";
import { useGroupLiveSync } from "./useGroupLiveSync";
import { useStrategies } from "./useStrategies";
import { useTradeGroupDetail } from "./useTradeGroupDetail";
import { useTradeGroups, type GroupPatch } from "./useTradeGroups";
import {
  useSelectionUrlSync,
  useWorkspaceSelection,
} from "./useWorkspaceSelection";

export default function StrategiesPage() {
  const { privacyMode } = usePrivacy();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [groupFilter, setGroupFilter] = useState<GroupFilter>("active");
  const [groupSort, setGroupSort] = useState<GroupSort>("name_grouped");

  const selection = useWorkspaceSelection();
  const { setStrategyId, setGroupId } = selection;
  const onDeepLink = useCallback(
    (strategyId: number, groupId: number) => {
      setStrategyId(strategyId);
      setGroupId(groupId);
    },
    [setStrategyId, setGroupId],
  );
  const strategyData = useStrategies({
    showArchived,
    deepLink: selection.deepLink,
    onDeepLink,
  });
  const { strategies } = strategyData;

  // The operator's choice resolved against the loaded lists: a selection that
  // is no longer present falls back to the first entry.
  const selectedStrategyId = resolveSelection(selection.strategyId, strategies);
  const selectedStrategy = useMemo(
    () =>
      strategies.find((strategy) => strategy.id === selectedStrategyId) ?? null,
    [selectedStrategyId, strategies],
  );
  const groupData = useTradeGroups(
    selectedStrategy?.name ?? null,
    !strategyData.loading,
  );
  const { groups } = groupData;
  // While the groups of the current strategy are still loading, keep the
  // operator's group so a deep-linked detail loads in parallel.
  const selectedGroupId =
    groups === null
      ? selection.groupId
      : resolveSelection(selection.groupId, groups);
  useSelectionUrlSync(selectedStrategyId, selectedGroupId);

  const detail = useTradeGroupDetail(selectedGroupId);
  const focus = useFocusMode(selectedGroupId);
  const liveSync = useGroupLiveSync(detail.reloadExecutions);

  const sections = useMemo(
    () => groupSections(groups ?? [], groupFilter, groupSort),
    [groups, groupFilter, groupSort],
  );

  // Draggable widths for the two list panes. Fed into each grid's leading
  // `grid-template-columns` track via a CSS custom property so the responsive
  // and focus-mode collapse behavior is preserved. Persisted per-device.
  const strategyColumn = useResizableColumn({
    storageKey: "trade_tagging_strategy_col_width",
    defaultWidth: 240,
    minWidth: 180,
    maxWidth: 520,
  });
  const groupsColumn = useResizableColumn({
    storageKey: "trade_tagging_groups_col_width",
    defaultWidth: 320,
    minWidth: 240,
    maxWidth: 680,
  });

  // Every write clears the banners first so a stale message never outlives
  // the action that follows it.
  const begin = () => {
    setError(null);
    setMessage(null);
  };

  const createStrategy = async (name: string) => {
    if (!name.trim()) throw new Error("Strategy value is required.");
    begin();
    const created = await strategyData.create(name.trim());
    setMessage("Created strategy.");
    setStrategyId(created.id);
  };

  const setStrategyArchived = async (
    strategy: Parameters<typeof strategyData.setArchived>[0],
    archived: boolean,
  ) => {
    begin();
    await strategyData.setArchived(strategy, archived);
    setMessage(archived ? "Archived strategy." : "Unarchived strategy.");
  };

  const createGroup = async (name: string, notes: string) => {
    if (!selectedStrategyId)
      throw new Error("Select a strategy before creating a trade group.");
    if (!name.trim()) throw new Error("Trade group name is required.");
    begin();
    const created = await groupData.create({
      name: name.trim(),
      notes: notes.trim() || null,
      strategy_id: selectedStrategyId,
    });
    setMessage(`Created trade group #${created.id}.`);
    setGroupId(created.id);
  };

  const saveGroup = async (body: GroupPatch) => {
    if (selectedGroupId == null) return;
    begin();
    await groupData.patch(selectedGroupId, body);
    setMessage("Trade group updated.");
    // A group moved to another strategy leaves the current list; follow it so
    // it stays selected (the strategy selection reloads the group list).
    if ("strategy_id" in body && body.strategy_id !== null) {
      setStrategyId(body.strategy_id as number);
    } else {
      await groupData.reload();
    }
    await detail.reloadDetail();
  };

  const deleteGroup = () => {
    if (selectedGroupId == null) return;
    if (
      !window.confirm(
        `Delete trade group #${selectedGroupId}? This will unassign all executions.`,
      )
    )
      return;
    begin();
    const id = selectedGroupId;
    groupData
      .remove(id)
      .then(() => {
        setMessage(`Deleted trade group #${id}.`);
        setGroupId(null);
      })
      .catch((err: unknown) =>
        setError(errorMessage(err, "Failed to delete group.")),
      );
  };

  const reloadGroups = () => {
    void groupData.reload().catch(() => {});
  };

  const pageError =
    error ?? strategyData.error ?? groupData.error ?? detail.error;
  const focusActive = focus.focusActive;

  return (
    <div className="flex min-h-0 flex-1 flex-col space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">Strategies</h2>
        <p className="text-xs text-gray-500">
          Manage strategies and their trade groups. Assign trades from the{" "}
          <a
            href="/trades"
            className="text-blue-600 underline hover:text-blue-800"
          >
            Trades
          </a>{" "}
          page.
        </p>
      </div>

      {strategyData.loading && (
        <p className="text-sm text-gray-600">Loading workspace...</p>
      )}
      {pageError && <p className="text-sm text-red-600">{pageError}</p>}
      {message && <p className="text-sm text-green-700">{message}</p>}

      <div
        className={`grid min-h-0 flex-1 grid-cols-1 ${
          strategyColumn.isDragging
            ? ""
            : "transition-[grid-template-columns,column-gap] duration-300 ease-in-out"
        } ${
          focusActive
            ? "gap-0 lg:grid-cols-[0fr_1fr]"
            : "gap-4 lg:grid-cols-[var(--col-strategy)_1fr]"
        }`}
        style={
          focusActive
            ? undefined
            : ({
                "--col-strategy": `${strategyColumn.width}px`,
              } as CSSProperties)
        }
      >
        <StrategyListPane
          strategies={strategies}
          selectedId={selectedStrategyId}
          onSelect={setStrategyId}
          showArchived={showArchived}
          onShowArchived={setShowArchived}
          onCreate={createStrategy}
          onSetArchived={setStrategyArchived}
          column={strategyColumn}
          focusActive={focusActive}
          onError={setError}
        />

        {/* Column 2: Trade Groups + Detail */}
        <section className="flex min-h-0 flex-col rounded border border-gray-200 bg-white p-3">
          <div
            className={`grid min-h-0 flex-1 grid-cols-1 ${
              groupsColumn.isDragging
                ? ""
                : "transition-[grid-template-columns,column-gap] duration-300 ease-in-out"
            } ${
              focusActive
                ? "gap-0 xl:grid-cols-[0fr_1fr]"
                : "gap-4 xl:grid-cols-[var(--col-groups)_1fr]"
            }`}
            style={
              focusActive
                ? undefined
                : ({
                    "--col-groups": `${groupsColumn.width}px`,
                  } as CSSProperties)
            }
          >
            <GroupListPane
              strategy={selectedStrategy}
              groups={groups}
              sections={sections}
              loading={groupData.loading}
              selectedId={selectedGroupId}
              onSelect={setGroupId}
              filter={groupFilter}
              onFilter={setGroupFilter}
              sort={groupSort}
              onSort={setGroupSort}
              onCreate={createGroup}
              column={groupsColumn}
              focusActive={focusActive}
              privacyMode={privacyMode}
              onError={setError}
            />

            {/* Group detail */}
            <div className="min-h-0 overflow-y-auto">
              {!detail.detail && selectedGroupId == null && (
                <div className="flex h-full items-center justify-center text-sm text-gray-400">
                  Select a trade group to view details.
                </div>
              )}
              {detail.detail && (
                <GroupDetailPane
                  key={detail.detail.id}
                  detail={detail.detail}
                  executions={detail.executions}
                  strategyName={selectedStrategy?.name ?? null}
                  strategies={strategies}
                  focusActive={focusActive}
                  onToggleFocus={focus.toggle}
                  privacyMode={privacyMode}
                  liveSync={liveSync}
                  onTagsChanged={() => {
                    void detail.reloadDetail();
                    reloadGroups();
                  }}
                  onTasksChanged={reloadGroups}
                  onSave={saveGroup}
                  onDelete={deleteGroup}
                />
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
