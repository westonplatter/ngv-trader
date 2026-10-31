import { useCallback, useEffect, useState } from "react";
import { usePrivacy } from "../contexts/usePrivacy";
import { PRIVACY_MASK } from "../utils/privacy";
import { useSseList } from "../hooks/useSseList";
import { api } from "../lib/api";
import type { Order } from "../types/orders";
import { formatDuration, parseTime } from "../utils/date";

const STATUS_CLASS: Record<string, string> = {
  queued: "text-yellow-700 bg-yellow-100",
  submitted: "text-blue-700 bg-blue-100",
  partially_filled: "text-indigo-700 bg-indigo-100",
  filled: "text-green-700 bg-green-100",
  cancelled: "text-gray-700 bg-gray-200",
  rejected: "text-red-700 bg-red-100",
  failed: "text-red-700 bg-red-100",
};
const TERMINAL_STATUSES = new Set([
  "filled",
  "cancelled",
  "rejected",
  "failed",
]);

function getEndMs(order: Order, nowMs: number): number {
  const completedMs = parseTime(order.completed_at);
  if (completedMs !== null) return completedMs;
  if (TERMINAL_STATUSES.has(order.status)) {
    return parseTime(order.updated_at) ?? nowMs;
  }
  return nowMs;
}

function computeQueueMs(order: Order, nowMs: number): number {
  const createdMs = parseTime(order.created_at) ?? nowMs;
  const submittedMs = parseTime(order.submitted_at);
  return (submittedMs ?? getEndMs(order, nowMs)) - createdMs;
}

function computeRunMs(order: Order, nowMs: number): number | null {
  const submittedMs = parseTime(order.submitted_at);
  if (submittedMs === null) return null;
  return getEndMs(order, nowMs) - submittedMs;
}

function computeTotalMs(order: Order, nowMs: number): number {
  const createdMs = parseTime(order.created_at) ?? nowMs;
  return getEndMs(order, nowMs) - createdMs;
}

export default function OrdersSideTable() {
  const { privacyMode } = usePrivacy();
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  const loadOrders = useCallback(() => api.get<Order[]>("/orders"), []);

  // Snapshot on mount, upsert from the orders stream, re-fetch on reconnect.
  const { items: orders, error } = useSseList<Order>({
    topic: "orders",
    load: loadOrders,
    key: (order) => order.id,
    cap: 20,
  });

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="min-w-0 h-full min-h-0 rounded border border-gray-300 bg-white p-3 flex flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Orders</h3>
      </div>

      {error && <p className="mb-2 text-xs text-red-600">Error: {error}</p>}

      <div className="min-h-0 flex-1 overflow-auto">
        <table className="min-w-full border-collapse text-xs">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-2 py-1 font-semibold text-gray-700">ID</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Order</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Status</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Queue</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Run</th>
              <th className="px-2 py-1 font-semibold text-gray-700">Total</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && (
              <tr>
                <td className="px-2 py-2 text-gray-500" colSpan={6}>
                  No orders yet.
                </td>
              </tr>
            )}
            {orders.map((order) => (
              <tr key={order.id} className="border-b border-gray-200 align-top">
                <td className="px-2 py-1 font-mono text-gray-800">
                  {order.id}
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {order.side} {privacyMode ? PRIVACY_MASK : order.quantity}{" "}
                  {order.symbol}
                  {order.contract_month ? ` ${order.contract_month}` : ""}
                </td>
                <td className="px-2 py-1">
                  <span
                    className={`rounded px-1.5 py-0.5 ${STATUS_CLASS[order.status] ?? "text-gray-700 bg-gray-100"}`}
                    title={
                      privacyMode
                        ? `filled ${PRIVACY_MASK} avg ${PRIVACY_MASK}`
                        : `filled ${order.filled_quantity} avg ${order.avg_fill_price ?? "n/a"}`
                    }
                  >
                    {order.status}
                  </span>
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeQueueMs(order, nowMs))}
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeRunMs(order, nowMs))}
                </td>
                <td className="px-2 py-1 text-gray-700">
                  {formatDuration(computeTotalMs(order, nowMs))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
