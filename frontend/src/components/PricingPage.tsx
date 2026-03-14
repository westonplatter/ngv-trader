import { useState } from "react";
import Plot from "react-plotly.js";

const PRICING_API_BASE = "/pricing-api";

interface OptionLeg {
  option_type: string;
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  trade_price: number | null;
  rate: number | null;
  underlying: number | null;
}

interface PnlRecord {
  spot_price: number;
  days_into_future: number;
  value: number;
}

interface ModelOutputs {
  min_dte: number;
  pnl_records: PnlRecord[];
  pnl_records_count: number;
}

interface ExpectedPnlResponse {
  model_inputs: Record<string, unknown>;
  model_outputs: ModelOutputs;
}

const LEGS: OptionLeg[] = [
  {
    option_type: "c",
    strike: 110,
    dte: 90,
    ivstart: 0.5,
    ivend: null,
    quantity: 1,
    trade_price: null,
    rate: null,
    underlying: null,
  },
  {
    option_type: "c",
    strike: 100,
    dte: 30,
    ivstart: 1.2,
    ivend: null,
    quantity: -1,
    trade_price: null,
    rate: null,
    underlying: null,
  },
  {
    option_type: "d1",
    strike: null,
    dte: 90,
    ivstart: 0,
    ivend: null,
    quantity: 0.1,
    trade_price: null,
    rate: null,
    underlying: null,
  },
];

export default function PricingPage() {
  const [spotPrice, setSpotPrice] = useState("103.13");
  const [spotMin, setSpotMin] = useState(() => (103.13 * 0.8).toFixed(2));
  const [spotMax, setSpotMax] = useState(() => (103.13 * 1.2).toFixed(2));
  const [dayStep, setDayStep] = useState("1");
  const [strikeStep, setStrikeStep] = useState("1");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pnlData, setPnlData] = useState<ExpectedPnlResponse | null>(null);

  const handleSubmit = async () => {
    const spot = parseFloat(spotPrice);
    const sMin = parseFloat(spotMin);
    const sMax = parseFloat(spotMax);

    if (isNaN(spot) || isNaN(sMin) || isNaN(sMax)) {
      setError("Spot price, min, and max are required.");
      return;
    }

    setLoading(true);
    setError(null);
    setPnlData(null);

    const daysIntoFuture = Math.max(...LEGS.map((l) => l.dte));

    try {
      const res = await fetch(`${PRICING_API_BASE}/expected-pnl`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spot_price: spot,
          legs: LEGS,
          spot_min: sMin,
          spot_max: sMax,
          days_into_future: daysIntoFuture,
          day_step: parseInt(dayStep) || 1,
          strike_step: parseFloat(strikeStep) || 1,
        }),
      });
      if (!res.ok) {
        const body = await res.text();
        throw new Error(`HTTP ${res.status}: ${body}`);
      }
      const data: ExpectedPnlResponse = await res.json();
      setPnlData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const plotTraces = buildPlotTraces(pnlData);

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-xl font-bold mb-4">Pricing — Expected PnL</h1>

      {/* Legs summary */}
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Legs
        </h2>
        <table className="text-sm border border-gray-200 rounded w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-3 py-1.5 text-left">Type</th>
              <th className="px-3 py-1.5 text-left">Strike</th>
              <th className="px-3 py-1.5 text-left">DTE</th>
              <th className="px-3 py-1.5 text-left">IV</th>
              <th className="px-3 py-1.5 text-left">Qty</th>
            </tr>
          </thead>
          <tbody>
            {LEGS.map((leg, i) => (
              <tr key={i} className="border-t border-gray-100">
                <td className="px-3 py-1.5">{leg.option_type}</td>
                <td className="px-3 py-1.5">{leg.strike ?? "—"}</td>
                <td className="px-3 py-1.5">{leg.dte}</td>
                <td className="px-3 py-1.5">
                  {leg.option_type === "d1"
                    ? "—"
                    : `${(leg.ivstart * 100).toFixed(0)}%`}
                </td>
                <td className="px-3 py-1.5">
                  {leg.quantity > 0 ? `+${leg.quantity}` : leg.quantity}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Inputs */}
      <div className="flex items-end gap-4 mb-6">
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Spot Price</span>
          <input
            type="number"
            step="any"
            value={spotPrice}
            onChange={(e) => {
              const val = e.target.value;
              setSpotPrice(val);
              const n = parseFloat(val);
              if (!isNaN(n)) {
                setSpotMin((n * 0.8).toFixed(2));
                setSpotMax((n * 1.2).toFixed(2));
              }
            }}
            className="border border-gray-300 rounded px-2 py-1.5 w-28"
            placeholder="e.g. 100"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Spot Min</span>
          <input
            type="number"
            step="any"
            value={spotMin}
            onChange={(e) => setSpotMin(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 w-28"
            placeholder="e.g. 80"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Spot Max</span>
          <input
            type="number"
            step="any"
            value={spotMax}
            onChange={(e) => setSpotMax(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 w-28"
            placeholder="e.g. 130"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Day Step</span>
          <input
            type="number"
            step="1"
            min="1"
            value={dayStep}
            onChange={(e) => setDayStep(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 w-20"
          />
        </label>
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Strike Step</span>
          <input
            type="number"
            step="any"
            min="0.01"
            value={strikeStep}
            onChange={(e) => setStrikeStep(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 w-20"
          />
        </label>
        <button
          onClick={handleSubmit}
          disabled={loading}
          className="bg-black text-white text-sm font-medium rounded px-4 py-1.5 hover:bg-gray-800 disabled:opacity-50"
        >
          {loading ? "Computing..." : "Calculate PnL"}
        </button>
      </div>

      {error && (
        <div className="text-red-600 text-sm mb-4 p-3 bg-red-50 rounded">
          {error}
        </div>
      )}

      {/* Chart */}
      {plotTraces && (
        <Plot
          data={plotTraces.data}
          layout={{
            title: "Expected PnL Over Time",
            xaxis: { title: "Spot Price" },
            yaxis: { title: "PnL" },
            height: 500,
            margin: { t: 40, r: 30, b: 50, l: 60 },
            showlegend: true,
            legend: { orientation: "v", x: 1.02, y: 1 },
          }}
          config={{ responsive: true }}
          style={{ width: "100%" }}
        />
      )}
    </div>
  );
}

function buildPlotTraces(data: ExpectedPnlResponse | null) {
  if (!data?.model_outputs?.pnl_records?.length) return null;

  const records = data.model_outputs.pnl_records;

  // Group records by days_into_future
  const byDay = new Map<number, { spots: number[]; values: number[] }>();
  for (const r of records) {
    let entry = byDay.get(r.days_into_future);
    if (!entry) {
      entry = { spots: [], values: [] };
      byDay.set(r.days_into_future, entry);
    }
    entry.spots.push(r.spot_price);
    entry.values.push(r.value);
  }

  const days = [...byDay.keys()].sort((a, b) => a - b);

  // Sample ~10 evenly spaced days for readability
  const step = Math.max(1, Math.floor(days.length / 10));
  const sampled = days.filter(
    (_, i) => i % step === 0 || i === days.length - 1,
  );

  const traces = sampled.map((day) => {
    const entry = byDay.get(day)!;
    // Sort by spot price
    const paired = entry.spots.map((s, i) => ({ s, v: entry.values[i] }));
    paired.sort((a, b) => a.s - b.s);

    return {
      x: paired.map((p) => p.s),
      y: paired.map((p) => p.v),
      type: "scatter" as const,
      mode: "lines" as const,
      name: `Day ${day}`,
    };
  });

  return { data: traces };
}
