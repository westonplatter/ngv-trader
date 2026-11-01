// One execution row. The Trade Group, Tags, and Tasks cells render only on
// the row that owns its group (the combo summary, or the earliest fill), so a
// spread reads as one trade.

import { Link } from "react-router-dom";
import { ibCodesTitle, parseIbCodes } from "../../lib/ibCodes";
import { tradeRowItem } from "../../lib/tags";
import {
  formatExecutedAt,
  rowGroupId,
  rowGroupKey,
  rowSymbol,
} from "../../lib/trades/view";
import type { TradeExecutionRow } from "../../types/trades";
import { makeFormatters } from "../../utils/maskedFormatters";
import TagChips from "../TagChips";
import TaskQuickAdd from "../TaskQuickAdd";
import TradeGroupCell from "./TradeGroupCell";

const STATUS_CLASS: Record<string, string> = {
  filled: "bg-emerald-100 text-emerald-800",
  partial: "bg-blue-100 text-blue-800",
  cancelled: "bg-zinc-200 text-zinc-800",
  expired: "bg-purple-100 text-purple-800",
  assigned: "bg-orange-100 text-orange-800",
  exercised: "bg-teal-100 text-teal-800",
  unknown: "bg-gray-100 text-gray-800",
  unsettled: "bg-amber-100 text-amber-800",
};

function execRoleBadge(role: string): { label: string; className: string } {
  if (role === "combo_summary") {
    return { label: "COMBO", className: "bg-indigo-100 text-indigo-800" };
  }
  if (role === "leg") {
    return { label: "LEG", className: "bg-amber-100 text-amber-800" };
  }
  return { label: "—", className: "bg-gray-100 text-gray-700" };
}

function lifecycleClass(lifecycle: string): string {
  if (lifecycle === "Open") return "bg-green-100 text-green-800";
  if (lifecycle === "Close") return "bg-red-100 text-red-800";
  return "bg-purple-100 text-purple-800";
}

export interface TradeRowProps {
  row: TradeExecutionRow;
  ownsGroupCell: boolean;
  groupLabel: string | null;
  showDetails: boolean;
  privacyMode: boolean;
  selected: boolean;
  isHighlighted: boolean;
  isSymbolHighlighted: boolean;
  onToggleSelected: (groupKey: string) => void;
  onToggleHighlight: (groupKey: string) => void;
  onToggleSymbolHighlight: (symbol: string | null) => void;
  onAssigned: () => void;
  onChanged: () => void;
}

function ParentExecCell({
  row,
  groupKey,
  isHighlighted,
  privacyMode,
  onToggleHighlight,
}: Pick<
  TradeRowProps,
  "row" | "isHighlighted" | "privacyMode" | "onToggleHighlight"
> & { groupKey: string }) {
  const fmt = makeFormatters(privacyMode);
  const isParentRow = row.exec_role === "combo_summary";
  const parentId =
    row.parent_ib_exec_id ?? (isParentRow ? row.ib_exec_id : null);
  if (!parentId) return <span className="text-gray-400">—</span>;
  const baseClass = isHighlighted
    ? "bg-yellow-200 text-yellow-900"
    : isParentRow
      ? "text-gray-400 hover:text-gray-600"
      : "text-blue-600 hover:text-blue-800";
  return (
    <button
      type="button"
      onClick={() => onToggleHighlight(groupKey)}
      className={`rounded px-1.5 py-0.5 hover:bg-yellow-100 ${baseClass}`}
      title={
        isParentRow
          ? "This row is the parent — click to highlight the group"
          : "Highlight sibling executions"
      }
    >
      {isParentRow && (
        <span className="mr-1" aria-hidden="true">
          ⤴
        </span>
      )}
      {fmt.masked(parentId)}
    </button>
  );
}

function CodesCell({ codes }: { codes: string | null }) {
  if (!codes) return <span className="text-xs text-gray-400">—</span>;
  return (
    <span className="group/codes relative inline-block">
      <span
        className="cursor-default rounded bg-slate-100 px-2 py-0.5 font-mono text-xs font-medium text-slate-700"
        title={ibCodesTitle(codes)}
      >
        {codes}
      </span>
      <span className="pointer-events-none absolute left-0 top-full z-20 mt-1 hidden w-max max-w-xs rounded bg-gray-900 px-2 py-1 text-xs text-white shadow-lg group-hover/codes:block">
        {parseIbCodes(codes).map(({ code, label }) => (
          <span key={code} className="block">
            <span className="font-mono font-semibold">{code}</span> — {label}
          </span>
        ))}
      </span>
    </span>
  );
}

export default function TradeRow(props: TradeRowProps) {
  const {
    row,
    ownsGroupCell,
    groupLabel,
    showDetails,
    privacyMode,
    selected,
    isHighlighted,
    isSymbolHighlighted,
    onToggleSelected,
    onToggleHighlight,
    onToggleSymbolHighlight,
    onAssigned,
    onChanged,
  } = props;
  const fmt = makeFormatters(privacyMode);
  const groupKey = rowGroupKey(row);
  const symbol = rowSymbol(row);
  const role = execRoleBadge(row.exec_role);
  const item = tradeRowItem(row);

  return (
    <tr
      className={`border-b border-gray-200 ${
        isHighlighted ? "bg-yellow-50" : "hover:bg-gray-50"
      }`}
    >
      <td className="px-2 py-2">
        {ownsGroupCell && item && (
          <input
            type="checkbox"
            aria-label="Select order"
            checked={selected}
            onChange={() => onToggleSelected(groupKey)}
          />
        )}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-gray-800">
        {row.account_alias ?? `Account ${row.account_id}`}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-gray-700">
        {formatExecutedAt(row.executed_at)}
      </td>
      <td
        onDoubleClick={() => onToggleSymbolHighlight(symbol)}
        title="Double-click to highlight matching contracts"
        className={`cursor-pointer select-none whitespace-nowrap px-3 py-2 font-medium ${
          isSymbolHighlighted ? "bg-red-200 text-red-900" : "text-gray-800"
        }`}
      >
        {symbol}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs">
        <span className={`rounded px-1.5 py-0.5 font-medium ${role.className}`}>
          {role.label}
        </span>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs">
        {row.trade_lifecycle ? (
          <span
            className={`rounded px-1.5 py-0.5 font-medium ${lifecycleClass(row.trade_lifecycle)}`}
          >
            {row.trade_lifecycle}
          </span>
        ) : (
          <span className="text-gray-400">—</span>
        )}
      </td>
      <td className="whitespace-nowrap px-1 py-2 text-xs text-gray-700">
        {row.sec_type ?? "-"}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
        {row.side ?? "-"}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-xs text-gray-700">
        {fmt.quantity(row.quantity)}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-gray-700">
        {fmt.money(row.price, "-")}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-gray-700">
        {fmt.money(row.realized_pnl, "-")}
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[row.trade_status] ?? "bg-gray-100 text-gray-800"}`}
        >
          {row.trade_status}
        </span>
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <CodesCell codes={row.ib_codes} />
      </td>
      <td className="px-3 py-2">
        {ownsGroupCell ? (
          <TradeGroupCell
            tradeId={row.trade_id}
            accountId={row.account_id}
            contractDisplayName={
              row.trade_contract_display_name ?? row.contract_display
            }
            assignedTradeGroupId={rowGroupId(row)}
            groupLabel={groupLabel}
            onAssigned={onAssigned}
            unsettled={row.settled === false}
            ibExecId={row.ib_exec_id}
          />
        ) : null}
      </td>
      <td className="px-3 py-2">
        {ownsGroupCell ? (
          <TagChips item={item} tags={row.tags ?? []} onChanged={onChanged} />
        ) : null}
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        {ownsGroupCell ? (
          <TaskQuickAdd
            item={item}
            openCount={row.open_task_count ?? 0}
            onCreated={onChanged}
          />
        ) : null}
      </td>
      <td className="max-w-[200px] truncate whitespace-nowrap px-3 py-2 font-mono text-xs">
        <ParentExecCell
          row={row}
          groupKey={groupKey}
          isHighlighted={isHighlighted}
          privacyMode={privacyMode}
          onToggleHighlight={onToggleHighlight}
        />
      </td>
      <td className="max-w-[160px] truncate whitespace-nowrap px-3 py-2 text-xs text-gray-600">
        {row.trade_order_ref ?? "-"}
      </td>
      {showDetails && (
        <>
          <td className="max-w-[200px] truncate whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-600">
            {fmt.masked(row.ib_exec_id)}
          </td>
          <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-gray-600">
            {row.con_id ? (
              <Link
                // Range defaults to "all" when con_id is set.
                to={`/trades?con_id=${row.con_id}&cols=all`}
                className="text-blue-600 hover:underline"
                title="Search all trades for this Contract ID (all time, all accounts)"
              >
                {row.con_id}
              </Link>
            ) : (
              "-"
            )}
          </td>
        </>
      )}
    </tr>
  );
}
