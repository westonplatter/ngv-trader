import { useCallback, useEffect, useState } from "react";
import Plot from "react-plotly.js";
import { API_BASE_URL } from "../config";
import ComboboxInput, { type ComboboxOption } from "./ComboboxInput";

const PRICING_API_BASE = "/pricing-api";
const INSTRUMENTS = ["CL", "NQ", "ES"] as const;

// --- Types ---

interface FuturesContract {
  con_id: number;
  symbol: string;
  local_symbol: string;
  display_name: string;
  contract_expiry: string;
  contract_month: string;
  dte: number;
  bid: number | null;
  ask: number | null;
  last: number | null;
  close: number | null;
  volume: number | null;
  open_interest: number | null;
}

interface OptionContract {
  con_id: number;
  symbol: string;
  display_name: string;
  sec_type: string;
  strike: number;
  right: "C" | "P";
  contract_expiry: string;
  dte: number;
  underlying_con_id: number;
  bid: number | null;
  ask: number | null;
  last: number | null;
  iv: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  und_price: number | null;
}

interface LegRow {
  id: string;
  optionType: "c" | "p" | "d1" | "cash";
  selectedConId: number | null;
  contractLabel: string;
  strike: number | null;
  dte: number;
  ivstart: number;
  quantity: number;
  tradePrice: number | null;
  bid: number | null;
  ask: number | null;
  undPrice: number | null;
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

function createEmptyLeg(): LegRow {
  return {
    id: crypto.randomUUID(),
    optionType: "c",
    selectedConId: null,
    contractLabel: "",
    strike: null,
    dte: 0,
    ivstart: 0,
    quantity: 1,
    tradePrice: null,
    bid: null,
    ask: null,
    undPrice: null,
  };
}

function midPrice(bid: number | null, ask: number | null): number | null {
  if (bid != null && ask != null) return (bid + ask) / 2;
  return bid ?? ask ?? null;
}

// --- Main Component ---

export default function PricingPage() {
  // Instrument & futures
  const [instrument, setInstrument] = useState<string>("CL");
  const [futuresContracts, setFuturesContracts] = useState<FuturesContract[]>(
    [],
  );
  const [futuresLoading, setFuturesLoading] = useState(false);

  // Options
  const [availableOptions, setAvailableOptions] = useState<OptionContract[]>(
    [],
  );
  const [optionsLoading, setOptionsLoading] = useState(false);

  // Inputs
  const [spotPrice, setSpotPrice] = useState("");
  const [spotMin, setSpotMin] = useState("");
  const [spotMax, setSpotMax] = useState("");
  const [dayStep, setDayStep] = useState("1");
  const [strikeStep, setStrikeStep] = useState("1");

  // Legs
  const [legs, setLegs] = useState<LegRow[]>([createEmptyLeg()]);

  // Results
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pnlData, setPnlData] = useState<ExpectedPnlResponse | null>(null);

  // --- Fetch term structure on instrument change ---
  useEffect(() => {
    setFuturesLoading(true);
    setFuturesContracts([]);
    setAvailableOptions([]);

    fetch(`${API_BASE_URL}/futures/${instrument}/term-structure?front_n=12`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: FuturesContract[]) => {
        setFuturesContracts(data);
        // Auto-set spot price from front month
        if (data.length > 0) {
          const price = data[0].last ?? data[0].close ?? 0;
          setSpotPrice(price.toFixed(2));
          setSpotMin((price * 0.8).toFixed(2));
          setSpotMax((price * 1.2).toFixed(2));
        }
      })
      .catch((err) => setError(err.message))
      .finally(() => setFuturesLoading(false));
  }, [instrument]);

  // --- Fetch ALL options for this instrument (across all underlyings) ---
  useEffect(() => {
    setOptionsLoading(true);
    setAvailableOptions([]);
    fetch(`${API_BASE_URL}/futures/${instrument}/options`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: OptionContract[]) => {
        setAvailableOptions(data);
      })
      .catch((err) => setError(err.message))
      .finally(() => setOptionsLoading(false));
  }, [instrument]);

  // --- Leg handlers ---
  const updateLeg = useCallback((id: string, updates: Partial<LegRow>) => {
    setLegs((prev) =>
      prev.map((leg) => (leg.id === id ? { ...leg, ...updates } : leg)),
    );
  }, []);

  const removeLeg = useCallback((id: string) => {
    setLegs((prev) => prev.filter((leg) => leg.id !== id));
  }, []);

  const addLeg = useCallback(() => {
    setLegs((prev) => [...prev, createEmptyLeg()]);
  }, []);

  // --- Kick off a targeted price fetch for a contract without pricing data ---
  const fetchPriceForContract = useCallback(async (conId: number) => {
    try {
      const res = await fetch(`${API_BASE_URL}/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_type: "market_data.snapshot",
          payload: { con_ids: [conId] },
          source: "pricing-ui",
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (err) {
      setError(
        `Failed to queue price fetch: ${err instanceof Error ? err.message : String(err)}`,
      );
    }
  }, []);

  // --- Submit ---
  const handleSubmit = async () => {
    const spot = parseFloat(spotPrice);
    const sMin = parseFloat(spotMin);
    const sMax = parseFloat(spotMax);

    if (isNaN(spot) || isNaN(sMin) || isNaN(sMax)) {
      setError("Spot price, min, and max are required.");
      return;
    }
    if (legs.length === 0) {
      setError("Add at least one leg.");
      return;
    }

    setLoading(true);
    setError(null);
    setPnlData(null);

    const apiLegs = legs.map((leg) => ({
      option_type: leg.optionType,
      strike: leg.strike,
      dte: leg.dte,
      ivstart: leg.ivstart,
      ivend: null,
      quantity: leg.quantity,
      trade_price: leg.tradePrice,
      rate: null,
      underlying: null,
    }));

    const daysIntoFuture = Math.max(...legs.map((l) => l.dte), 1);

    try {
      const res = await fetch(`${PRICING_API_BASE}/expected-pnl`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          spot_price: spot,
          legs: apiLegs,
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
    <div className="max-w-7xl mx-auto">
      <h1 className="text-xl font-bold mb-4">Pricing — Expected PnL</h1>

      {/* Instrument & Spot */}
      <div className="flex items-end gap-4 mb-4">
        <label className="flex flex-col text-sm">
          <span className="text-gray-600 mb-1">Instrument</span>
          <select
            value={instrument}
            onChange={(e) => setInstrument(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5"
          >
            {INSTRUMENTS.map((sym) => (
              <option key={sym} value={sym}>
                /{sym}
              </option>
            ))}
          </select>
        </label>
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
          />
        </label>
      </div>

      {/* Dynamic Legs Table */}
      <div className="mb-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Legs
        </h2>
        <table className="text-sm border border-gray-200 rounded w-full">
          <thead className="bg-gray-50">
            <tr>
              <th className="px-2 py-1.5 text-left w-10">#</th>
              <th className="px-2 py-1.5 text-left w-20">Type</th>
              <th className="px-2 py-1.5 text-left w-36">Strike</th>
              <th className="px-2 py-1.5 text-left w-36">DTE</th>
              <th className="px-2 py-1.5 text-left w-16">Qty</th>
              <th className="px-2 py-1.5 text-left w-20">IV</th>
              <th className="px-2 py-1.5 text-left w-20">Und</th>
              <th className="px-2 py-1.5 text-left w-20">Bid</th>
              <th className="px-2 py-1.5 text-left w-20">Ask</th>
              <th className="px-2 py-1.5 text-left w-20">Mid</th>
              <th className="px-2 py-1.5 w-8"></th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg, idx) => (
              <LegRowComponent
                key={leg.id}
                leg={leg}
                index={idx}
                availableOptions={availableOptions}
                futuresContracts={futuresContracts}
                optionsLoading={optionsLoading}
                futuresLoading={futuresLoading}
                onUpdate={updateLeg}
                onRemove={removeLeg}
                onFetchPrice={fetchPriceForContract}
              />
            ))}
          </tbody>
        </table>
        <button
          onClick={addLeg}
          className="mt-2 text-sm text-blue-600 hover:text-blue-800 font-medium"
        >
          + Add Leg
        </button>
      </div>

      {/* Controls */}
      <div className="flex items-end gap-4 mb-6">
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
            margin: { t: 40, r: 120, b: 50, l: 60 },
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

// --- Leg Row Sub-component ---

function LegRowComponent({
  leg,
  index,
  availableOptions,
  futuresContracts,
  optionsLoading,
  futuresLoading,
  onUpdate,
  onRemove,
  onFetchPrice,
}: {
  leg: LegRow;
  index: number;
  availableOptions: OptionContract[];
  futuresContracts: FuturesContract[];
  optionsLoading: boolean;
  futuresLoading: boolean;
  onUpdate: (id: string, updates: Partial<LegRow>) => void;
  onRemove: (id: string) => void;
  onFetchPrice: (conId: number) => void;
}) {
  const isD1 = leg.optionType === "d1";
  const isCash = leg.optionType === "cash";
  const isOption = !isD1 && !isCash;
  const mid = midPrice(leg.bid, leg.ask);

  // --- Option leg: filter by type → strikes → DTEs ---
  const rightFilter = leg.optionType === "c" ? "C" : "P";
  const optionsForType = isOption
    ? availableOptions.filter((o) => o.right === rightFilter)
    : [];

  const uniqueStrikes = [...new Set(optionsForType.map((o) => o.strike))].sort(
    (a, b) => a - b,
  );

  const strikeComboboxOptions: ComboboxOption<number>[] = uniqueStrikes.map(
    (s) => ({
      label: s.toFixed(2),
      value: String(s),
      data: s,
    }),
  );

  const optionsForStrike =
    leg.strike != null
      ? optionsForType.filter((o) => o.strike === leg.strike)
      : [];

  const dteOptions = optionsForStrike
    .map((o) => ({ dte: o.dte, con_id: o.con_id }))
    .sort((a, b) => a.dte - b.dte);

  // --- D1 leg: futures contract selector ---
  const futuresComboboxOptions: ComboboxOption<FuturesContract>[] =
    futuresContracts.map((f) => ({
      label: `${f.display_name} (DTE ${f.dte})`,
      value: String(f.con_id),
      data: f,
    }));

  // --- Shared helpers ---
  const hasPricingData = (contract: {
    bid: number | null;
    ask: number | null;
    iv?: number | null;
  }) =>
    contract.bid != null ||
    contract.ask != null ||
    (contract.iv != null && contract.iv !== undefined);

  const applyOptionContract = (contract: OptionContract) => {
    const m = midPrice(contract.bid, contract.ask);
    onUpdate(leg.id, {
      selectedConId: contract.con_id,
      strike: contract.strike,
      dte: contract.dte,
      ivstart: contract.iv ?? 0,
      bid: contract.bid,
      ask: contract.ask,
      tradePrice: m,
      undPrice: contract.und_price,
    });
    if (!hasPricingData(contract)) {
      onFetchPrice(contract.con_id);
    }
  };

  const handleStrikeSelect = (option: ComboboxOption<number>) => {
    const strike = option.data;
    const matching = optionsForType.filter((o) => o.strike === strike);
    const dtesForStrike = matching.sort((a, b) => a.dte - b.dte);

    if (dtesForStrike.length === 1) {
      applyOptionContract(dtesForStrike[0]);
    } else {
      onUpdate(leg.id, {
        strike,
        selectedConId: null,
        dte: 0,
        ivstart: 0,
        bid: null,
        ask: null,
        tradePrice: null,
        undPrice: null,
      });
    }
  };

  const handleDteSelect = (conId: number) => {
    const contract = availableOptions.find((o) => o.con_id === conId);
    if (!contract) return;
    applyOptionContract(contract);
  };

  const handleFuturesSelect = (option: ComboboxOption<FuturesContract>) => {
    const fut = option.data;
    const price = fut.last ?? fut.close ?? 0;
    const m = midPrice(fut.bid, fut.ask);
    onUpdate(leg.id, {
      selectedConId: fut.con_id,
      contractLabel: fut.display_name,
      strike: null,
      dte: fut.dte,
      ivstart: 0,
      bid: fut.bid,
      ask: fut.ask,
      tradePrice: m,
      undPrice: price,
    });
    if (!hasPricingData(fut)) {
      onFetchPrice(fut.con_id);
    }
  };

  return (
    <tr className="border-t border-gray-100">
      <td className="px-2 py-1.5 text-gray-400">{index + 1}</td>
      {/* Type */}
      <td className="px-2 py-1.5">
        <select
          value={leg.optionType}
          onChange={(e) => {
            const newType = e.target.value as LegRow["optionType"];
            onUpdate(leg.id, {
              optionType: newType,
              selectedConId: null,
              contractLabel: "",
              strike: null,
              dte: 0,
              ivstart: 0,
              bid: null,
              ask: null,
              tradePrice: null,
              undPrice: null,
            });
          }}
          className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
        >
          <option value="c">Call</option>
          <option value="p">Put</option>
          <option value="d1">D1</option>
          <option value="cash">Cash</option>
        </select>
      </td>
      {/* Strike / Futures selector */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <ComboboxInput
            options={futuresComboboxOptions}
            value={leg.contractLabel}
            onChange={handleFuturesSelect}
            onClear={() =>
              onUpdate(leg.id, {
                selectedConId: null,
                contractLabel: "",
                dte: 0,
                bid: null,
                ask: null,
                tradePrice: null,
                undPrice: null,
              })
            }
            placeholder={futuresLoading ? "Loading..." : "Select future..."}
            loading={futuresLoading}
          />
        ) : isCash ? (
          <input
            type="number"
            step="any"
            value={leg.strike ?? ""}
            onChange={(e) =>
              onUpdate(leg.id, {
                strike: e.target.value ? parseFloat(e.target.value) : null,
              })
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
            placeholder="Manual"
          />
        ) : (
          <ComboboxInput
            options={strikeComboboxOptions}
            value={leg.strike != null ? leg.strike.toFixed(2) : ""}
            onChange={handleStrikeSelect}
            onClear={() =>
              onUpdate(leg.id, {
                strike: null,
                selectedConId: null,
                dte: 0,
                ivstart: 0,
                bid: null,
                ask: null,
                tradePrice: null,
                undPrice: null,
              })
            }
            placeholder={optionsLoading ? "Loading..." : "Strike..."}
            loading={optionsLoading}
          />
        )}
      </td>
      {/* DTE */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <span className="text-gray-500 text-sm">
            {leg.dte ? `${leg.dte}d` : "—"}
          </span>
        ) : isCash ? (
          <input
            type="number"
            step="1"
            value={leg.dte || ""}
            onChange={(e) =>
              onUpdate(leg.id, { dte: parseInt(e.target.value) || 0 })
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
            placeholder="DTE"
          />
        ) : leg.strike == null ? (
          <span className="text-gray-400 text-xs">Pick strike first</span>
        ) : dteOptions.length === 0 ? (
          <span className="text-gray-400 text-xs">No DTEs</span>
        ) : (
          <select
            value={leg.selectedConId ?? ""}
            onChange={(e) => handleDteSelect(Number(e.target.value))}
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
          >
            <option value="">Select DTE...</option>
            {dteOptions.map((d) => (
              <option key={d.con_id} value={d.con_id}>
                {d.dte}d
              </option>
            ))}
          </select>
        )}
      </td>
      {/* Qty */}
      <td className="px-2 py-1.5">
        <input
          type="number"
          step="any"
          value={leg.quantity}
          onChange={(e) =>
            onUpdate(leg.id, { quantity: parseFloat(e.target.value) || 0 })
          }
          className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
        />
      </td>
      {/* IV */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <span className="text-gray-400">—</span>
        ) : (
          <input
            type="number"
            step="any"
            value={leg.ivstart || ""}
            onChange={(e) =>
              onUpdate(leg.id, { ivstart: parseFloat(e.target.value) || 0 })
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
          />
        )}
      </td>
      {/* Underlying price */}
      <td className="px-2 py-1.5 text-gray-500">
        {leg.undPrice?.toFixed(2) ?? "—"}
      </td>
      {/* Bid / Ask / Mid */}
      <td className="px-2 py-1.5 text-gray-500">
        {leg.bid?.toFixed(2) ??
          (leg.selectedConId ? (
            <span className="text-yellow-600 text-xs">fetching...</span>
          ) : (
            "—"
          ))}
      </td>
      <td className="px-2 py-1.5 text-gray-500">
        {leg.ask?.toFixed(2) ??
          (leg.selectedConId ? (
            <span className="text-yellow-600 text-xs">fetching...</span>
          ) : (
            "—"
          ))}
      </td>
      <td className="px-2 py-1.5">
        <input
          type="number"
          step="any"
          value={leg.tradePrice ?? mid ?? ""}
          onChange={(e) =>
            onUpdate(leg.id, {
              tradePrice: e.target.value ? parseFloat(e.target.value) : null,
            })
          }
          className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
        />
      </td>
      <td className="px-2 py-1.5">
        <button
          onClick={() => onRemove(leg.id)}
          className="text-gray-400 hover:text-red-500 text-xs"
        >
          ✕
        </button>
      </td>
    </tr>
  );
}

// --- Chart builder ---

function buildPlotTraces(data: ExpectedPnlResponse | null) {
  if (!data?.model_outputs?.pnl_records?.length) return null;

  const records = data.model_outputs.pnl_records;

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

  const step = Math.max(1, Math.floor(days.length / 10));
  const sampled = days.filter(
    (_, i) => i % step === 0 || i === days.length - 1,
  );

  const traces = sampled.map((day) => {
    const entry = byDay.get(day)!;
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
