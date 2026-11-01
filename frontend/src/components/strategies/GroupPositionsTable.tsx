// The Open Positions table of a group's detail, with the totals row on top
// and account banding. Rows are already account-filtered and sorted.

import { formatMarkTime } from "../../lib/markTime";
import {
  accountBands,
  positionAccountLabel,
  positionGreeks,
  positionTotals,
  type SumCount,
} from "../../lib/strategies/groupPositions";
import type { GroupOpenPosition } from "../../types/tradeGroups";
import { formatGreek, formatMoney, formatPercent } from "../../utils/number";
import { PRIVACY_MASK, formatRelativeReturn } from "../../utils/privacy";

const TH_RIGHT = "px-2 py-1 text-right font-medium";
const TD_MONO = "px-2 py-1 text-right font-mono text-gray-700";

function TotalCell({
  total,
  privacyMode,
  format,
  colorize = false,
}: {
  total: SumCount;
  privacyMode: boolean;
  format: (value: number) => string;
  colorize?: boolean;
}) {
  const className = colorize
    ? `px-2 py-1 text-right font-mono ${
        total.count === 0
          ? "text-gray-400"
          : total.sum >= 0
            ? "text-emerald-700"
            : "text-red-700"
      }`
    : TD_MONO;
  return (
    <td className={className}>
      {privacyMode ? PRIVACY_MASK : total.count === 0 ? "—" : format(total.sum)}
    </td>
  );
}

function FreshnessBadge({ pos }: { pos: GroupOpenPosition }) {
  if (pos.source === "live" && pos.live_is_stale) {
    return (
      <span
        className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800"
        title="Live TWS overlay is older than the latest settled snapshot. Refresh Live (TWS) to update."
      >
        stale
        {(pos.mark_ts ?? pos.live_fetched_at)
          ? ` ${formatMarkTime(pos.mark_ts ?? pos.live_fetched_at)}`
          : ""}
      </span>
    );
  }
  if (pos.source === "live") {
    return (
      <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[11px] font-medium text-emerald-800">
        live{pos.mark_ts ? ` ${formatMarkTime(pos.mark_ts)}` : ""}
      </span>
    );
  }
  return (
    <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[11px] font-medium text-gray-600">
      settled
    </span>
  );
}

function PositionRow({
  pos,
  band,
  privacyMode,
}: {
  pos: GroupOpenPosition;
  band: number | undefined;
  privacyMode: boolean;
}) {
  const qtyClass =
    pos.position > 0
      ? "text-emerald-700"
      : pos.position < 0
        ? "text-red-700"
        : "text-gray-600";
  const pnlClass =
    pos.fifo_pnl_unrealized == null
      ? "text-gray-400"
      : pos.fifo_pnl_unrealized >= 0
        ? "text-emerald-700"
        : "text-red-700";
  // A stale live overlay (settled snapshot is newer) must not be shown as
  // current: blank the live-only cells and flag the badge as "stale".
  const liveStale = pos.live_is_stale;
  const livePnlClass =
    liveStale || pos.live_unrealized == null
      ? "text-gray-400"
      : pos.live_unrealized >= 0
        ? "text-emerald-700"
        : "text-red-700";
  // Position-level greeks in underlying units: per-contract value × signed
  // quantity × the contract multiplier (see positionGreeks).
  const { delta, gamma } = positionGreeks(pos);
  const basis = Math.abs(pos.avg_cost * pos.position);
  const mask = (text: string) => (privacyMode ? PRIVACY_MASK : text);
  return (
    <tr
      className={`border-t border-gray-100 ${band === 1 ? "bg-gray-50" : "bg-white"}`}
    >
      <td className="px-2 py-1 text-gray-700">{positionAccountLabel(pos)}</td>
      <td className="px-2 py-1 text-gray-700">{pos.right ?? "—"}</td>
      <td className={TD_MONO}>{pos.dte ?? "—"}</td>
      <td className={TD_MONO}>{pos.strike ?? "—"}</td>
      <td className={`px-2 py-1 text-right font-mono ${qtyClass}`}>
        {privacyMode ? PRIVACY_MASK : pos.position}
      </td>
      <td className={TD_MONO}>{mask(formatGreek(delta))}</td>
      <td className={TD_MONO}>{mask(formatGreek(gamma))}</td>
      <td className={TD_MONO}>{mask(formatPercent(liveStale ? null : pos.iv))}</td>
      <td className={TD_MONO}>{mask(formatMoney(pos.avg_cost))}</td>
      <td className={TD_MONO}>{mask(formatMoney(pos.avg_cost * pos.position))}</td>
      <td className={TD_MONO}>
        {mask(pos.mark_price == null ? "—" : formatMoney(pos.mark_price))}
      </td>
      <td className={TD_MONO}>
        {mask(liveStale || pos.mark == null ? "—" : formatMoney(pos.mark))}
      </td>
      <td className={TD_MONO}>
        {mask(
          pos.position_value == null ? "—" : formatMoney(pos.position_value),
        )}
      </td>
      <td className={`px-2 py-1 text-right font-mono ${pnlClass}`}>
        {privacyMode
          ? formatRelativeReturn(pos.fifo_pnl_unrealized, basis)
          : pos.fifo_pnl_unrealized == null
            ? "—"
            : formatMoney(pos.fifo_pnl_unrealized)}
      </td>
      <td className={`px-2 py-1 text-right font-mono ${livePnlClass}`}>
        {privacyMode
          ? liveStale
            ? PRIVACY_MASK
            : formatRelativeReturn(pos.live_unrealized, basis)
          : liveStale || pos.live_unrealized == null
            ? "—"
            : formatMoney(pos.live_unrealized)}
      </td>
      <td className="px-2 py-1 text-gray-500">{pos.as_of_date ?? "—"}</td>
      <td className="px-2 py-1">
        <FreshnessBadge pos={pos} />
      </td>
    </tr>
  );
}

export default function GroupPositionsTable({
  positions,
  totalCount,
  accountFiltered,
  privacyMode,
}: {
  // Visible (account-filtered, sorted) positions.
  positions: GroupOpenPosition[];
  // Count across all accounts, shown as "of N" when filtered.
  totalCount: number;
  accountFiltered: boolean;
  privacyMode: boolean;
}) {
  const totals = positionTotals(positions);
  const bands = accountBands(positions);
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
          Open Positions ({positions.length}
          {accountFiltered ? ` of ${totalCount}` : ""})
        </h5>
      </div>
      {positions.length === 0 && (
        <p className="mb-3 text-xs text-gray-400">
          No open positions linked to this group.
        </p>
      )}
      {positions.length > 0 && (
        <div className="mb-4 max-h-[260px] overflow-auto rounded border border-gray-200">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-gray-50 text-gray-600">
              <tr>
                <th className="px-2 py-1 font-medium">Account</th>
                <th className="px-2 py-1 font-medium">Call/Put</th>
                <th className={TH_RIGHT}>DTE</th>
                <th className={TH_RIGHT}>Strike</th>
                <th className={TH_RIGHT}>Qty</th>
                <th
                  className={TH_RIGHT}
                  title="Delta × quantity × contract multiplier (underlying units, e.g. barrels or shares). Futures and stock count as 1.0 delta per unit."
                >
                  Delta
                </th>
                <th
                  className={TH_RIGHT}
                  title="Gamma × quantity × contract multiplier (underlying units)."
                >
                  Gamma
                </th>
                <th className={TH_RIGHT}>IV</th>
                <th className={TH_RIGHT}>Avg Cost</th>
                <th
                  className={TH_RIGHT}
                  title="Avg cost × signed quantity (multiplier-inclusive). Positive = debit paid, negative = credit received."
                >
                  Cost Basis
                </th>
                <th className={TH_RIGHT}>Mark</th>
                <th className={TH_RIGHT}>Live Mark</th>
                <th className={TH_RIGHT}>Value</th>
                <th className={TH_RIGHT}>Unrealized</th>
                <th className={TH_RIGHT}>Live Unrealized</th>
                <th className="px-4 py-1 font-medium">As of</th>
                <th className="px-2 py-1 font-medium">Source</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-t border-b-2 border-gray-300 bg-gray-50 font-medium">
                <td className="px-2 py-1 text-gray-700">Total</td>
                <td className="px-2 py-1"></td>
                <td className="px-2 py-1 text-right"></td>
                <td className="px-2 py-1 text-right"></td>
                <td className="px-2 py-1 text-right"></td>
                <TotalCell total={totals.delta} privacyMode={privacyMode} format={formatGreek} />
                <TotalCell total={totals.gamma} privacyMode={privacyMode} format={formatGreek} />
                <td className="px-2 py-1 text-right"></td>
                <TotalCell total={totals.avgCost} privacyMode={privacyMode} format={formatMoney} />
                <TotalCell total={totals.costBasis} privacyMode={privacyMode} format={formatMoney} />
                <td className="px-2 py-1 text-right"></td>
                <td className="px-2 py-1 text-right"></td>
                <TotalCell total={totals.value} privacyMode={privacyMode} format={formatMoney} />
                <TotalCell total={totals.unrealized} privacyMode={privacyMode} format={formatMoney} colorize />
                <TotalCell total={totals.liveUnrealized} privacyMode={privacyMode} format={formatMoney} colorize />
                <td className="px-2 py-1"></td>
                <td className="px-2 py-1"></td>
              </tr>
              {positions.map((pos) => (
                <PositionRow
                  key={`${pos.account_id}-${pos.con_id}`}
                  pos={pos}
                  band={bands.get(pos.account_id)}
                  privacyMode={privacyMode}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
