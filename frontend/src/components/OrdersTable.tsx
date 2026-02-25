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

const COLUMNS: { key: keyof Order; label: string }[] = [
  { key: "id", label: "Order ID" },
  { key: "account_alias", label: "Account" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "side", label: "Side" },
  { key: "quantity", label: "Qty" },
  { key: "status", label: "Status" },
  { key: "contract_month", label: "Contract Month" },
  { key: "local_symbol", label: "Local Symbol" },
  { key: "ib_order_id", label: "IB Order ID" },
  { key: "filled_quantity", label: "Filled Qty" },
  { key: "avg_fill_price", label: "Avg Fill Px" },
  { key: "created_at", label: "Created At" },
  { key: "updated_at", label: "Updated At" },
];

export default function OrdersTable() {
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            {COLUMNS.map((col) => (
              <th
                key={col.key}
                className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap"
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {orderedRows.map((row) =>
            row.kind === "group" ? (
              <tr key={`group-${row.key}`} className="bg-gray-50">
                <td
                  className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-gray-600"
                  colSpan={COLUMNS.length}
                >
                  {row.label}
                </td>
              </tr>
            ) : (
              <tr
                key={row.order.id}
                className="border-b border-gray-200 hover:bg-gray-50"
              >
                {COLUMNS.map((col) => (
                  <td key={col.key} className="px-3 py-2 whitespace-nowrap">
                    {row.order[col.key] ?? "—"}
                  </td>
                ))}
              </tr>
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
