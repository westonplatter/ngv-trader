import { useEffect, useMemo, useState } from "react";

interface Order {
  id: number;
  account_id: number;
  account_alias: string | null;
  symbol: string;
  sec_type: string;
  side: string;
  quantity: number;
  status: string;
  contract_month: string | null;
  local_symbol: string | null;
  ib_order_id: number | null;
  filled_quantity: number;
  avg_fill_price: number | null;
  created_at: string;
  updated_at: string;
}

const STATUS_CLASS: Record<string, string> = {
  queued: "bg-amber-100 text-amber-800",
  submitting: "bg-orange-100 text-orange-800",
  submitted: "bg-blue-100 text-blue-800",
  partially_filled: "bg-indigo-100 text-indigo-800",
  reconcile_required: "bg-purple-100 text-purple-800",
  filled: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-zinc-200 text-zinc-800",
  rejected: "bg-rose-100 text-rose-800",
  failed: "bg-red-100 text-red-800",
};

function formatTime(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "—";
  return new Date(parsed).toLocaleString();
}

export default function OrdersTable() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);

  const orderedRows = useMemo(() => {
    const sorted = [...orders].sort((a, b) => {
      const aMs = Date.parse(a.created_at);
      const bMs = Date.parse(b.created_at);
      if (Number.isNaN(aMs) && Number.isNaN(bMs)) return b.id - a.id;
      if (Number.isNaN(aMs)) return 1;
      if (Number.isNaN(bMs)) return -1;
      return bMs - aMs;
    });

    const rows: Array<
      | { kind: "group"; key: string; label: string }
      | { kind: "order"; order: Order }
    > = [];
    let currentGroupKey = "";
    for (const order of sorted) {
      const createdDate = new Date(order.created_at);
      const groupKey = Number.isNaN(createdDate.getTime())
        ? "Unknown date"
        : `${createdDate.getFullYear()}-${String(createdDate.getMonth() + 1).padStart(2, "0")}-${String(createdDate.getDate()).padStart(2, "0")}`;
      if (groupKey !== currentGroupKey) {
        currentGroupKey = groupKey;
        rows.push({
          kind: "group",
          key: groupKey,
          label:
            groupKey === "Unknown date"
              ? "Unknown date"
              : createdDate.toLocaleDateString(undefined, {
                  weekday: "short",
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                }),
        });
      }
      rows.push({ kind: "order", order });
    }
    return rows;
  }, [orders]);

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch("http://localhost:8000/api/v1/orders")
        .then((res) => {
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          return res.json();
        })
        .then((data: Order[]) => {
          if (!active) return;
          setOrders(data);
          setError(null);
          setLastUpdated(Date.now());
        })
        .catch((err: Error) => {
          if (!active) return;
          setError(err.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    };

    load();
    const timer = window.setInterval(load, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  if (loading) return <p className="text-gray-500">Loading orders...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (orders.length === 0)
    return <p className="text-gray-500">No orders found.</p>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900">Orders</h2>
        <span className="text-xs text-gray-500">
          Auto-refresh 3s
          {lastUpdated
            ? ` · Last update ${new Date(lastUpdated).toLocaleTimeString()}`
            : ""}
        </span>
      </div>

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Order
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Contract
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Status
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Fills
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Broker IDs
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Lifecycle
              </th>
            </tr>
          </thead>
          <tbody>
            {orderedRows.map((row) =>
              row.kind === "group" ? (
                <tr key={`group-${row.key}`} className="bg-gray-50">
                  <td
                    className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-600"
                    colSpan={6}
                  >
                    {row.label}
                  </td>
                </tr>
              ) : (
                <tr
                  key={row.order.id}
                  className="border-b border-gray-200 hover:bg-gray-50"
                >
                  <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                    <div className="font-medium">#{row.order.id}</div>
                    <div className="text-xs text-gray-500">
                      {row.order.account_alias ??
                        `Account ${row.order.account_id}`}
                    </div>
                    <div className="text-xs text-gray-500">
                      {row.order.side} {row.order.quantity} {row.order.symbol}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    <div>{row.order.sec_type}</div>
                    <div className="text-xs text-gray-500">
                      {row.order.local_symbol ??
                        row.order.contract_month ??
                        "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[row.order.status] ?? "bg-gray-100 text-gray-800"}`}
                    >
                      {row.order.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    <div>
                      {row.order.filled_quantity} / {row.order.quantity}
                    </div>
                    <div className="text-xs text-gray-500">
                      Avg {row.order.avg_fill_price ?? "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    <div className="text-xs">
                      order {row.order.ib_order_id ?? "—"}
                    </div>
                    <div className="text-xs">
                      perm {row.order.ib_perm_id ?? "—"}
                    </div>
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                    <div className="text-xs">
                      Created {formatTime(row.order.created_at)}
                    </div>
                    <div className="text-xs">
                      Updated {formatTime(row.order.updated_at)}
                    </div>
                  </td>
                </tr>
              ),
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
