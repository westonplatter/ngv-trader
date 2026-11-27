// Working broker orders on contracts the selected group holds. Matched by
// account and contract (a combo by any leg), not assigned, so an order on a
// contract two groups hold shows under both, marked shared.

import { useCallback, useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useSSE } from "../../lib/events";
import type { GroupWorkingOrder } from "../../types/tradeGroups";
import { formatDateTime } from "../../utils/date";
import { makeFormatters } from "../../utils/maskedFormatters";

const TH_RIGHT = "px-2 py-1 text-right font-medium";

function sideClass(side: string): string {
  return /^(BOT|BUY)$/i.test(side) ? "text-emerald-700" : "text-red-700";
}

export default function GroupWorkingOrdersTable({
  groupId,
  accountFilter,
  privacyMode,
}: {
  groupId: number;
  accountFilter: number | null;
  privacyMode: boolean;
}) {
  const fmt = makeFormatters(privacyMode);
  const [loaded, setLoaded] = useState<{
    groupId: number;
    rows: GroupWorkingOrder[];
  } | null>(null);

  const load = useCallback(() => {
    api
      .get<GroupWorkingOrder[]>(`/trade-groups/${groupId}/working-orders`)
      .then((rows) => setLoaded({ groupId, rows }))
      .catch(() => setLoaded({ groupId, rows: [] }));
  }, [groupId]);

  useEffect(load, [load]);
  useSSE("orders", load);

  const all = loaded?.groupId === groupId ? loaded.rows : [];
  const rows =
    accountFilter == null
      ? all
      : all.filter((row) => row.order.account_id === accountFilter);

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <h5 className="text-xs font-semibold uppercase tracking-wide text-gray-600">
          Working Orders ({rows.length}
          {accountFilter != null ? ` of ${all.length}` : ""})
        </h5>
      </div>
      {rows.length === 0 && (
        <p className="mb-3 text-xs text-gray-400">
          No working orders on this group's open positions.
        </p>
      )}
      {rows.length > 0 && (
        <div className="mb-4 max-h-[240px] overflow-auto rounded border border-gray-200">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-gray-50 text-gray-600">
              <tr>
                <th className="px-2 py-1 font-medium">When</th>
                <th className="px-2 py-1 font-medium">Account</th>
                <th className="px-2 py-1 font-medium">Contract</th>
                <th className={TH_RIGHT}>Side</th>
                <th className={TH_RIGHT}>Qty</th>
                <th className={TH_RIGHT}>Remaining</th>
                <th className={TH_RIGHT}>Limit</th>
                <th className="px-2 py-1 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ order, matched_con_ids, shared_with }) => {
                const matched = new Set(matched_con_ids);
                return (
                  <tr
                    key={order.id}
                    className="border-t border-gray-100 align-top"
                  >
                    <td className="px-2 py-1 text-gray-700">
                      {formatDateTime(order.submitted_at ?? order.created_at)}
                    </td>
                    <td className="px-2 py-1 text-gray-700">
                      {order.account_alias ?? `Account ${order.account_id}`}
                    </td>
                    <td className="px-2 py-1 text-gray-800">
                      {order.contract_display_name}
                      {shared_with.length > 0 && (
                        <span
                          className="ml-1 rounded bg-amber-100 px-1 py-0.5 text-[10px] uppercase text-amber-800"
                          title={`Also held by ${shared_with.map((g) => g.name).join(", ")}. The order may be for either group.`}
                        >
                          shared
                        </span>
                      )}
                      {order.legs.length > 0 && (
                        <ul className="mt-0.5 space-y-0.5 text-[11px] text-gray-500">
                          {order.legs.map((leg) => (
                            <li
                              key={leg.leg_index}
                              className={
                                matched.has(leg.con_id)
                                  ? "font-medium text-gray-800"
                                  : undefined
                              }
                            >
                              {leg.quantity > 0 ? "+" : ""}
                              {fmt.quantity(leg.quantity)}{" "}
                              {leg.contract_display_name}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td
                      className={`px-2 py-1 text-right ${sideClass(order.side)}`}
                    >
                      {order.side}
                    </td>
                    <td className="px-2 py-1 text-right text-gray-700">
                      {fmt.quantity(order.quantity)}
                    </td>
                    <td className="px-2 py-1 text-right text-gray-700">
                      {order.remaining_quantity == null
                        ? "—"
                        : fmt.quantity(order.remaining_quantity)}
                    </td>
                    <td className="px-2 py-1 text-right text-gray-700">
                      {order.limit_price == null
                        ? order.order_type
                        : order.limit_price}
                    </td>
                    <td className="px-2 py-1">
                      <span
                        className={
                          order.status === "reconcile_required"
                            ? "rounded bg-amber-100 px-1 py-0.5 text-[10px] uppercase text-amber-800"
                            : "rounded bg-sky-50 px-1 py-0.5 text-[10px] uppercase text-sky-800"
                        }
                      >
                        {order.status === "reconcile_required"
                          ? "needs reconcile"
                          : order.status.replace("_", " ")}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
