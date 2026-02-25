import { useEffect, useState } from "react";

interface Position {
  id: number;
  account_alias: string;
  con_id: number;
  symbol: string | null;
  sec_type: string | null;
  exchange: string | null;
  primary_exchange: string | null;
  currency: string | null;
  local_symbol: string | null;
  trading_class: string | null;
  last_trade_date: string | null;
  strike: number | null;
  right: string | null;
  multiplier: string | null;
  position: number;
  avg_cost: number;
  fetched_at: string;
}

function formatExpiry(value: string | null | undefined): string {
  if (!value) return "\u2014";
  // YYYYMMDD → YYYY-MM-DD
  if (value.length === 8 && !value.includes("-")) {
    return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return value;
}

const COLUMNS: { key: keyof Position; label: string }[] = [
  { key: "account_alias", label: "Account" },
  { key: "con_id", label: "Con ID" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "currency", label: "Currency" },
  { key: "local_symbol", label: "Local Symbol" },
  { key: "trading_class", label: "Trading Class" },
  { key: "last_trade_date", label: "Last Trade Date" },
  { key: "strike", label: "Strike" },
  { key: "right", label: "Call/Put" },
  { key: "multiplier", label: "Multiplier" },
  { key: "position", label: "Position" },
  { key: "avg_cost", label: "Avg Cost" },
];

export default function PositionsTable() {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("http://localhost:8000/api/v1/positions")
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then(setPositions)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-gray-500">Loading positions...</p>;
  if (error) return <p className="text-red-600">Error: {error}</p>;
  if (positions.length === 0)
    return <p className="text-gray-500">No positions found.</p>;

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
          {positions.map((pos) => (
            <tr
              key={pos.id}
              className="border-b border-gray-200 hover:bg-gray-50"
            >
              {COLUMNS.map((col) => (
                <td key={col.key} className="px-3 py-2 whitespace-nowrap">
                  {col.key === "last_trade_date"
                    ? formatExpiry(pos[col.key] as string | null)
                    : (pos[col.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
