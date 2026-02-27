import { useEffect, useMemo, useState } from "react";
import { usePrivacy } from "../contexts/PrivacyContext";
import { PRIVACY_MASK } from "../utils/privacy";

const API_BASE_URL = "http://localhost:8000/api/v1";

interface Order {
  id: number;
  account_id: number;
  account_alias: string | null;
  con_id: number | null;
  symbol: string;
  sec_type: string;
  exchange: string;
  currency: string;
  side: string;
  quantity: number;
  order_type: string;
  limit_price: number | null;
  tif: string;
  status: string;
  contract_month: string | null;
  contract_expiry: string | null;
  option_right: string | null;
  option_strike: string | null;
  contract_display_name: string;
  local_symbol: string | null;
  ib_order_id: number | null;
  ib_perm_id: number | null;
  filled_quantity: number;
  avg_fill_price: number | null;
  created_at: string;
  updated_at: string;
}

type OrderFilter = "all" | "working" | "closed";

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
const WORKING_STATUSES = new Set([
  "queued",
  "submitting",
  "submitted",
  "partially_filled",
  "reconcile_required",
]);
const TERMINAL_STATUSES = new Set([
  "filled",
  "cancelled",
  "rejected",
  "failed",
]);

function formatExpiry(value: string | null | undefined): string {
  if (!value) return "—";
  if (value.length === 8 && !value.includes("-")) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

function formatDate(value: string): string {
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return "—";
  return new Date(parsed).toLocaleDateString();
}

function getDisplayedSymbol(order: Order): string {
  return (order.symbol || "").trim().toUpperCase();
}

export default function OrdersTable() {
  const { privacyMode } = usePrivacy();
  const [orders, setOrders] = useState<Order[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [filter, setFilter] = useState<OrderFilter>("all");
  const [cancelMessage, setCancelMessage] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const [cancelingOrderIds, setCancelingOrderIds] = useState<Set<number>>(
    new Set(),
  );
  const [symbolRegexFilter, setSymbolRegexFilter] = useState("");

  const loadOrders = () => {
    fetch(`${API_BASE_URL}/orders`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: Order[]) => {
        setOrders(data);
        setError(null);
      })
      .catch((err: Error) => {
        setError(err.message);
      })
      .finally(() => {
        setLoading(false);
      });
  };

  const symbolFilter = useMemo(() => {
    const raw = symbolRegexFilter.trim();
    if (!raw)
      return { regex: null as RegExp | null, error: null as string | null };
    try {
      return { regex: new RegExp(raw, "i"), error: null as string | null };
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid regex";
      return { regex: null as RegExp | null, error: message };
    }
  }, [symbolRegexFilter]);

  const filteredOrders = useMemo(() => {
    let next = orders;
    if (filter === "working") {
      next = next.filter((order) => WORKING_STATUSES.has(order.status));
    } else if (filter === "closed") {
      next = next.filter((order) => TERMINAL_STATUSES.has(order.status));
    }
    if (symbolFilter.regex) {
      next = next.filter((order) =>
        symbolFilter.regex!.test(getDisplayedSymbol(order)),
      );
    }
    return next;
  }, [filter, orders, symbolFilter]);

  const workingCount = useMemo(
    () => orders.filter((order) => WORKING_STATUSES.has(order.status)).length,
    [orders],
  );

  const terminalCount = useMemo(
    () => orders.filter((order) => TERMINAL_STATUSES.has(order.status)).length,
    [orders],
  );

  const sortedOrders = useMemo(() => {
    return [...filteredOrders].sort((a, b) => {
      const aMs = Date.parse(a.created_at);
      const bMs = Date.parse(b.created_at);
      if (Number.isNaN(aMs) && Number.isNaN(bMs)) return b.id - a.id;
      if (Number.isNaN(aMs)) return 1;
      if (Number.isNaN(bMs)) return -1;
      return bMs - aMs;
    });
  }, [filteredOrders]);

  useEffect(() => {
    let active = true;

    const load = () => {
      fetch(`${API_BASE_URL}/orders`)
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

  const kickOffOrderSync = async () => {
    setSyncing(true);
    setSyncMessage(null);
    setSyncError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/orders/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Manual order fetch/sync from Orders page.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: { job_id: number; status: string } = await res.json();
      setSyncMessage(`Queued order sync job #${data.job_id} (${data.status}).`);
      window.setTimeout(() => loadOrders(), 1000);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown sync error";
      setSyncError(message);
    } finally {
      setSyncing(false);
    }
  };

  const cancelQueuedOrder = async (orderId: number) => {
    if (cancelingOrderIds.has(orderId)) return;
    setCancelMessage(null);
    setCancelError(null);
    setCancelingOrderIds((prev) => {
      const next = new Set(prev);
      next.add(orderId);
      return next;
    });
    try {
      const res = await fetch(`${API_BASE_URL}/orders/${orderId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text: "Cancelled from Orders UI",
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(body || `HTTP ${res.status}`);
      }
      const data: Order = await res.json();
      setCancelMessage(`Order #${data.id} is now '${data.status}'.`);
      loadOrders();
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Unknown cancel error";
      setCancelError(message);
    } finally {
      setCancelingOrderIds((prev) => {
        const next = new Set(prev);
        next.delete(orderId);
        return next;
      });
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Orders</h2>
          <p className="text-xs text-gray-500">
            Working {workingCount} · Terminal {terminalCount}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => {
              void kickOffOrderSync();
            }}
            disabled={syncing}
            className="rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50"
          >
            {syncing ? "Queueing..." : "Pull Broker Orders"}
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {(["all", "working", "closed"] as const).map((nextFilter) => (
          <button
            key={nextFilter}
            onClick={() => setFilter(nextFilter)}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              filter === nextFilter
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            {nextFilter}
          </button>
        ))}
      </div>

      {loading && <p className="text-gray-500">Loading orders...</p>}
      {error && <p className="text-red-600">Error: {error}</p>}
      {cancelMessage && (
        <p className="text-sm text-green-700">{cancelMessage}</p>
      )}
      {cancelError && (
        <p className="text-sm text-red-600">Cancel error: {cancelError}</p>
      )}
      {syncMessage && <p className="text-sm text-green-700">{syncMessage}</p>}
      {syncError && (
        <p className="text-sm text-red-600">Sync error: {syncError}</p>
      )}
      {symbolFilter.error && (
        <p className="text-sm text-red-600">
          Symbol regex error: {symbolFilter.error}
        </p>
      )}

      <div className="overflow-x-auto rounded border border-gray-200 bg-white">
        <table className="min-w-full border-collapse text-sm">
          <thead>
            <tr className="bg-gray-100 text-left">
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Date
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Order ID
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Con ID
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap align-top">
                <div className="space-y-1">
                  <input
                    value={symbolRegexFilter}
                    onChange={(e) => setSymbolRegexFilter(e.target.value)}
                    placeholder="Regex filter"
                    className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs font-normal text-gray-700"
                  />
                  <div>Symbol</div>
                </div>
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Perm ID
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Account
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Action
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Quantity
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Order Type
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                TIF
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Limit Price
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Contract
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Call/Put
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Strike
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Expiry
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Status
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Fills
              </th>
              <th className="px-3 py-2 font-semibold text-gray-700 whitespace-nowrap">
                Controls
              </th>
            </tr>
          </thead>
          <tbody>
            {!loading && sortedOrders.length === 0 && (
              <tr>
                <td
                  colSpan={18}
                  className="px-3 py-6 text-center text-gray-500"
                >
                  {filter === "working"
                    ? "No working orders right now."
                    : filter === "closed"
                      ? "No closed orders right now."
                      : "No orders found."}
                </td>
              </tr>
            )}
            {sortedOrders.map((order) => (
              <tr
                key={order.id}
                className={`border-b border-gray-200 hover:bg-gray-50 ${
                  WORKING_STATUSES.has(order.status) ? "bg-blue-50/40" : ""
                }`}
              >
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {formatDate(order.created_at)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                  {order.ib_order_id ?? "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                  {order.con_id ?? "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                  {getDisplayedSymbol(order) || "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                  {privacyMode ? PRIVACY_MASK : (order.ib_perm_id ?? "—")}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-800">
                  {order.account_alias ?? `Account ${order.account_id}`}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {order.side}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {privacyMode ? PRIVACY_MASK : order.quantity}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  <div>{order.order_type}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {order.tif}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {order.limit_price ?? "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  <div>{order.contract_display_name}</div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {order.option_right ?? "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {order.option_strike ?? "—"}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  {formatExpiry(order.contract_expiry)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_CLASS[order.status] ?? "bg-gray-100 text-gray-800"}`}
                  >
                    {order.status}
                  </span>
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-700">
                  <div>
                    {privacyMode
                      ? PRIVACY_MASK
                      : `${order.filled_quantity} / ${order.quantity}`}
                  </div>
                </td>
                <td className="px-3 py-2 whitespace-nowrap">
                  {order.status === "queued" ? (
                    <button
                      onClick={() => {
                        void cancelQueuedOrder(order.id);
                      }}
                      disabled={cancelingOrderIds.has(order.id)}
                      className="rounded border border-red-300 px-2 py-0.5 text-xs text-red-700 hover:bg-red-50 disabled:opacity-50"
                    >
                      {cancelingOrderIds.has(order.id)
                        ? "Cancelling..."
                        : "Cancel"}
                    </button>
                  ) : (
                    <span className="text-xs text-gray-400">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
