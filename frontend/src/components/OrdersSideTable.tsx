import { useEffect, useState } from "react";

interface OrderRow {
  id: number;
  symbol: string;
  side: string;
  quantity: number;
  contract_month: string | null;
  status: string;
  filled_quantity: number;
  avg_fill_price: number | null;
  created_at: string;
  submitted_at: string | null;
  completed_at: string | null;
  updated_at: string;
}

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

function parseTime(value: string | null): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatDuration(ms: number | null): string {
  if (ms === null) return "—";
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remMinutes = minutes % 60;
  return `${hours}h ${remMinutes}m`;
}

function getEndMs(order: OrderRow, nowMs: number): number {
  const completedMs = parseTime(order.completed_at);
  if (completedMs !== null) return completedMs;
  if (TERMINAL_STATUSES.has(order.status)) {
    return parseTime(order.updated_at) ?? nowMs;
  }
  return nowMs;
}

function computeQueueMs(order: OrderRow, nowMs: number): number {
  const createdMs = parseTime(order.created_at) ?? nowMs;
  const submittedMs = parseTime(order.submitted_at);
  return (submittedMs ?? getEndMs(order, nowMs)) - createdMs;
}

function computeRunMs(order: OrderRow, nowMs: number): number | null {
  const submittedMs = parseTime(order.submitted_at);
  if (submittedMs === null) return null;
  return getEndMs(order, nowMs) - submittedMs;
}

function computeTotalMs(order: OrderRow, nowMs: number): number {
  const createdMs = parseTime(order.created_at) ?? nowMs;
  return getEndMs(order, nowMs) - createdMs;
}

export default function OrdersSideTable() {
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch("http://localhost:8000/api/v1/orders")
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((rows: OrderRow[]) => {
          if (!active) return;
          setOrders(rows.slice(0, 20));
          setError(null);
        })
        .catch((err: Error) => {
          if (!active) return;
          setError(err.message);
        });
    };

    load();
    const timer = window.setInterval(load, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="min-w-0 h-full min-h-0 rounded border border-gray-300 bg-white p-3 flex flex-col">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900">Orders</h3>
        <span className="text-xs text-gray-500">Auto-refresh 2.5s</span>
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
                  {order.side} {order.quantity} {order.symbol}
                  {order.contract_month ? ` ${order.contract_month}` : ""}
                </td>
                <td className="px-2 py-1">
                  <span
                    className={`rounded px-1.5 py-0.5 ${STATUS_CLASS[order.status] ?? "text-gray-700 bg-gray-100"}`}
                    title={`filled ${order.filled_quantity} avg ${order.avg_fill_price ?? "n/a"}`}
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
