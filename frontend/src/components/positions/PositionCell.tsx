// One body cell of the positions table: picks the rendering for a column,
// masks dollar figures in privacy mode, and blanks live-overlay values when
// the row's overlay is stale.

import type React from "react";
import { Link } from "react-router-dom";
import { formatMarkTime } from "../../lib/markTime";
import {
  expiryForPosition,
  positionCostBasis,
  positionItem,
} from "../../lib/positions/view";
import type { Position } from "../../types/positions";
import { formatExpiry } from "../../utils/date";
import {
  formatDelta,
  formatGreek,
  formatMultiplier,
  formatPercent,
  formatStrike,
} from "../../utils/number";
import { makeFormatters } from "../../utils/maskedFormatters";
import TagChips from "../TagChips";
import TaskQuickAdd from "../TaskQuickAdd";
import TradeGroupSearchSelect from "../TradeGroupSearchSelect";
import {
  CELL_TINT,
  LIVE_OVERLAY_VALUE_KEYS,
  columnGroup,
  type PositionColumn,
} from "./columns";

export interface PositionCellProps {
  pos: Position;
  column: PositionColumn;
  privacyMode: boolean;
  onAssign: (pos: Position, groupId: number) => void;
  onUnassign: (pos: Position, groupId: number) => void;
  // Tags or tasks changed on this row; the page reloads the snapshot.
  onChanged: () => void;
}

function pnlClass(value: number | null): string {
  if (value == null) return "";
  return value >= 0 ? "text-emerald-700 font-medium" : "text-red-700 font-medium";
}

function FreshnessBadge({ pos }: { pos: Position }) {
  if (pos.source === "live" && pos.live_is_stale) {
    // Live snapshot predates the newer settled snapshot — flag as stale
    // (amber) with the age of the live data, so it never reads as a current
    // green "live" quote.
    const staleTs = formatMarkTime(pos.mark_ts ?? pos.live_fetched_at);
    return (
      <span
        className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800"
        title="Live TWS overlay is older than the latest settled (FlexQuery) snapshot. Refresh Live (TWS) to update."
      >
        stale{staleTs ? ` ${staleTs}` : ""}
      </span>
    );
  }
  if (pos.source === "live") {
    const ts = formatMarkTime(pos.mark_ts);
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800">
        live{ts ? ` ${ts}` : ""}
      </span>
    );
  }
  return (
    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
      settled
    </span>
  );
}

function TradeGroupsCell({
  pos,
  onAssign,
  onUnassign,
}: Pick<PositionCellProps, "pos" | "onAssign" | "onUnassign">) {
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap">
      {pos.trade_groups.map((group) => (
        <span
          key={group.id}
          className="inline-flex items-center gap-0.5 rounded bg-gray-100 px-1.5 py-0.5"
        >
          <Link
            to={`/strategies?trade_group_id=${group.id}`}
            className="text-blue-600 hover:underline"
          >
            {group.name}
          </Link>
          <button
            type="button"
            onClick={() => {
              if (
                window.confirm(
                  `Remove all fills of this position from "${group.name}"?`,
                )
              )
                onUnassign(pos, group.id);
            }}
            className="text-gray-400 hover:text-red-600"
            title="Remove position's fills from this trade group"
            aria-label={`Remove from ${group.name}`}
          >
            ×
          </button>
        </span>
      ))}
      <TradeGroupSearchSelect
        accountId={pos.account_id}
        contractDisplayName={pos.contract_display_name}
        onSelect={(group) => onAssign(pos, group.id)}
        renderTrigger={(open) => (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              open();
            }}
            className="rounded border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-400 hover:border-blue-300 hover:text-blue-600"
            title="Assign to trade group"
            aria-label="Assign to trade group"
          >
            {pos.trade_groups.length === 0 ? "+ Assign" : "+"}
          </button>
        )}
      />
    </span>
  );
}

// The value for every column that is plain text or a formatted number.
// Returns [content, extra class for the cell].
function cellContent(
  props: PositionCellProps,
): [React.ReactNode, string] {
  const { pos, column, privacyMode, onAssign, onUnassign, onChanged } = props;
  const key = column.key;
  const fmt = makeFormatters(privacyMode);
  const money = fmt.money;

  if (pos.live_is_stale && LIVE_OVERLAY_VALUE_KEYS.has(key)) {
    // Stale live overlay: blank the value so old TWS marks/greeks aren't
    // presented as current. The Freshness badge (source column) still renders
    // and flags the row as stale.
    return ["—", ""];
  }
  switch (key) {
    case "trade_groups":
      return [
        <TradeGroupsCell pos={pos} onAssign={onAssign} onUnassign={onUnassign} />,
        "",
      ];
    case "tags":
      return [
        <TagChips
          item={positionItem(pos)}
          tags={pos.tags ?? []}
          onChanged={onChanged}
        />,
        "",
      ];
    case "open_task_count":
      return [
        <TaskQuickAdd
          item={positionItem(pos)}
          openCount={pos.open_task_count ?? 0}
          onCreated={onChanged}
          tasksHref={`/tasks?symbol=${encodeURIComponent(pos.symbol ?? "")}`}
        />,
        "",
      ];
    case "position":
      return [fmt.quantity(pos.position), ""];
    case "last_trade_date":
      return [formatExpiry(pos.last_trade_date), ""];
    case "option_expiry_date":
      return [expiryForPosition(pos), ""];
    case "strike":
      return [pos.sec_type === "FUT" ? "—" : formatStrike(pos.strike), ""];
    case "multiplier":
      return [formatMultiplier(pos.multiplier), ""];
    case "avg_cost":
      return [money(pos.avg_cost), ""];
    case "mark_price":
      return [money(pos.mark_price), ""];
    case "position_value":
      return [money(pos.position_value), ""];
    case "fifo_pnl_unrealized":
      return [
        fmt.pnl(pos.fifo_pnl_unrealized, positionCostBasis(pos)),
        pnlClass(pos.fifo_pnl_unrealized),
      ];
    case "mark":
      return [money(pos.mark), ""];
    case "live_unrealized":
      return [
        fmt.pnl(pos.live_unrealized, positionCostBasis(pos)),
        pnlClass(pos.live_unrealized),
      ];
    case "iv":
      // IV is a risk metric, not dollar exposure — show in privacy.
      return [formatPercent(pos.iv), ""];
    case "delta":
      return [formatDelta(pos.delta), ""];
    case "gamma":
    case "theta":
    case "vega":
      return [formatGreek(pos[key]), ""];
    case "extrinsic_value":
    case "intrinsic_value":
      // Per-unit prices — mask like the other price columns.
      return [money(pos[key]), ""];
    case "source":
      return [<FreshnessBadge pos={pos} />, ""];
    case "contract_display_name":
      // Informational only — no link.
      return [pos.contract_display_name, ""];
    case "con_id":
      return [
        pos.con_id ? (
          <Link
            to={`/trades?con_id=${pos.con_id}`}
            className="font-mono text-blue-600 hover:underline"
            title="Search all trades for this Contract ID (all time, all accounts)"
          >
            {pos.con_id}
          </Link>
        ) : (
          "—"
        ),
        "",
      ];
    default:
      return [(pos[key] as React.ReactNode) ?? "—", ""];
  }
}

export default function PositionCell(props: PositionCellProps) {
  const [content, extraClass] = cellContent(props);
  return (
    <td
      className={`px-3 py-2 whitespace-nowrap ${CELL_TINT[columnGroup(props.column.key)]} ${extraClass}`}
    >
      {content}
    </td>
  );
}
