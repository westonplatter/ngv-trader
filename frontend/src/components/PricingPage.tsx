import { useCallback, useEffect, useRef, useState } from "react";
import Plot from "react-plotly.js";
import { API_BASE_URL } from "../config";
import { useSSE, type ConnectionStatus } from "../lib/events";
import ComboboxInput, { type ComboboxOption } from "./ComboboxInput";

const PRICING_API_BASE = "/pricing-api";
const INSTRUMENTS = ["CL", "NQ", "ES"] as const;

// --- Saved structure types ---

interface SavedStructure {
  id: number;
  name: string;
  instrument: string;
  legs: SavedLeg[];
  spot_price: number | null;
  created_at: string;
  updated_at: string;
}

interface SavedLeg {
  optionType: LegRow["optionType"];
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  tradePrice: number | null;
  bid: number | null;
  ask: number | null;
  undPrice: number | null;
  contractLabel: string;
  selectedConId: number | null;
  selectedExpiry: string | null;
  selectedTradingClass: string | null;
}

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

interface ChainEntry {
  symbol: string;
  trading_class: string;
  expiration: string;
  strike: number;
  right: "C" | "P";
  dte: number;
  underlying_con_id: number;
  exchange: string;
  sec_type: string;
  con_id: number | null;
  display_name: string;
  is_monthly: boolean;
  bid: number | null;
  ask: number | null;
  last: number | null;
  iv: number | null;
  delta: number | null;
  und_price: number | null;
  observed_at: string | null;
}

type FetchStatus = "idle" | "working" | "done" | "error";

interface LegRow {
  id: string;
  optionType: "c" | "p" | "d1" | "cash";
  selectedConId: number | null;
  contractLabel: string;
  selectedExpiry: string | null;
  selectedTradingClass: string | null;
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  tradePrice: number | null;
  bid: number | null;
  ask: number | null;
  undPrice: number | null;
  observedAt: string | null;
  fetchStatus: FetchStatus;
  fetchJobId: number | null;
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
    selectedExpiry: null,
    selectedTradingClass: null,
    strike: null,
    dte: 0,
    ivstart: 0,
    ivend: null,
    quantity: 1,
    tradePrice: null,
    bid: null,
    ask: null,
    undPrice: null,
    observedAt: null,
    fetchStatus: "idle",
    fetchJobId: null,
  };
}

function midPrice(bid: number | null, ask: number | null): number | null {
  if (bid != null && ask != null) return (bid + ask) / 2;
  return bid ?? ask ?? null;
}

// --- Expiration formatting ---
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function formatExpiration(expiration: string, isMonthly: boolean): string {
  if (expiration.length !== 8) return expiration;
  const y = parseInt(expiration.slice(0, 4));
  const m = parseInt(expiration.slice(4, 6)) - 1;
  const d = parseInt(expiration.slice(6, 8));
  if (isMonthly) return `${MONTHS[m]} ${y}`;
  return `${String(d).padStart(2, "0")}-${MONTHS[m]}-${y}`;
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
  const [availableOptions, setAvailableOptions] = useState<ChainEntry[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  // Inputs
  const [spotPrice, setSpotPrice] = useState("");
  const [spotMin, setSpotMin] = useState("");
  const [spotMax, setSpotMax] = useState("");
  const [dayStep, setDayStep] = useState("1");
  const [strikeStep, setStrikeStep] = useState("1");

  // Legs
  const [legs, setLegs] = useState<LegRow[]>([createEmptyLeg()]);

  // Saved structures
  const [savedStructures, setSavedStructures] = useState<SavedStructure[]>([]);
  const [loadedStructureId, setLoadedStructureId] = useState<number | null>(
    null,
  );

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

  // --- Fetch option chain catalog ---
  useEffect(() => {
    setOptionsLoading(true);
    setAvailableOptions([]);
    fetch(`${API_BASE_URL}/futures/${instrument}/chain`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: ChainEntry[]) => setAvailableOptions(data))
      .catch((err) => setError(err.message))
      .finally(() => setOptionsLoading(false));
  }, [instrument]);

  // --- Fetch saved structures ---
  const fetchSavedStructures = useCallback(() => {
    fetch(`${API_BASE_URL}/structures`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: SavedStructure[]) => setSavedStructures(data))
      .catch((err) => setError(err.message));
  }, []);

  useEffect(() => {
    fetchSavedStructures();
  }, [fetchSavedStructures]);

  // --- Structure serialization ---
  function legsToSaved(currentLegs: LegRow[]): SavedLeg[] {
    return currentLegs.map((leg) => ({
      optionType: leg.optionType,
      strike: leg.strike,
      dte: leg.dte,
      ivstart: leg.ivstart,
      ivend: leg.ivend,
      quantity: leg.quantity,
      tradePrice: leg.tradePrice,
      bid: leg.bid,
      ask: leg.ask,
      undPrice: leg.undPrice,
      contractLabel: leg.contractLabel,
      selectedConId: leg.selectedConId,
      selectedExpiry: leg.selectedExpiry,
      selectedTradingClass: leg.selectedTradingClass,
    }));
  }

  function savedLegsToRows(savedLegs: SavedLeg[]): LegRow[] {
    return savedLegs.map((sl) => ({
      id: crypto.randomUUID(),
      optionType: sl.optionType,
      strike: sl.strike,
      dte: sl.dte,
      ivstart: sl.ivstart,
      ivend: sl.ivend ?? null,
      quantity: sl.quantity,
      tradePrice: sl.tradePrice,
      bid: sl.bid,
      ask: sl.ask,
      undPrice: sl.undPrice,
      contractLabel: sl.contractLabel,
      selectedConId: sl.selectedConId,
      selectedExpiry: sl.selectedExpiry ?? null,
      selectedTradingClass: sl.selectedTradingClass ?? null,
      fetchStatus: "idle" as FetchStatus,
      fetchJobId: null,
    }));
  }

  // --- Structure handlers ---
  const handleLoadStructure = useCallback(
    (structureId: number) => {
      const s = savedStructures.find((x) => x.id === structureId);
      if (!s) return;
      setInstrument(s.instrument);
      setLegs(savedLegsToRows(s.legs));
      if (s.spot_price != null) {
        const p = s.spot_price;
        setSpotPrice(p.toFixed(2));
        setSpotMin((p * 0.8).toFixed(2));
        setSpotMax((p * 1.2).toFixed(2));
      }
      setLoadedStructureId(s.id);
    },
    [savedStructures],
  );

  const handleSave = useCallback(async () => {
    if (loadedStructureId == null) return;
    const spot = parseFloat(spotPrice);
    await fetch(`${API_BASE_URL}/structures/${loadedStructureId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name:
          savedStructures.find((s) => s.id === loadedStructureId)?.name ?? "",
        instrument,
        legs: legsToSaved(legs),
        spot_price: isNaN(spot) ? null : spot,
      }),
    });
    fetchSavedStructures();
  }, [
    loadedStructureId,
    instrument,
    legs,
    spotPrice,
    savedStructures,
    fetchSavedStructures,
  ]);

  const handleSaveAs = useCallback(async () => {
    const name = window.prompt("Enter a name for this structure:");
    if (!name) return;
    const spot = parseFloat(spotPrice);
    const res = await fetch(`${API_BASE_URL}/structures`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name,
        instrument,
        legs: legsToSaved(legs),
        spot_price: isNaN(spot) ? null : spot,
      }),
    });
    if (res.ok) {
      const created: SavedStructure = await res.json();
      setLoadedStructureId(created.id);
      fetchSavedStructures();
    }
  }, [instrument, legs, spotPrice, fetchSavedStructures]);

  const handleDeleteStructure = useCallback(async () => {
    if (loadedStructureId == null) return;
    if (!window.confirm("Delete this saved structure?")) return;
    await fetch(`${API_BASE_URL}/structures/${loadedStructureId}`, {
      method: "DELETE",
    });
    setLoadedStructureId(null);
    fetchSavedStructures();
  }, [loadedStructureId, fetchSavedStructures]);

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

  // --- Qualify + snapshot ---
  const fetchPriceForContract = useCallback(
    async (legId: string, entry: ChainEntry) => {
      setLegs((prev) =>
        prev.map((l) =>
          l.id === legId
            ? { ...l, fetchStatus: "working" as FetchStatus, fetchJobId: null }
            : l,
        ),
      );
      try {
        const jobPayload =
          entry.con_id != null
            ? {
                job_type: "market_data.snapshot",
                payload: { con_ids: [entry.con_id] },
                source: "pricing-ui",
              }
            : {
                job_type: "contracts.qualify_and_snapshot",
                payload: {
                  symbol: entry.symbol,
                  sec_type: entry.sec_type,
                  exchange: entry.exchange,
                  trading_class: entry.trading_class,
                  expiration: entry.expiration,
                  strike: entry.strike,
                  right: entry.right,
                },
                source: "pricing-ui",
              };
        const res = await fetch(`${API_BASE_URL}/jobs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(jobPayload),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const job = await res.json();
        setLegs((prev) =>
          prev.map((l) => (l.id === legId ? { ...l, fetchJobId: job.id } : l)),
        );
      } catch (err) {
        setLegs((prev) =>
          prev.map((l) =>
            l.id === legId ? { ...l, fetchStatus: "error" as FetchStatus } : l,
          ),
        );
        setError(
          `Failed to queue price fetch: ${err instanceof Error ? err.message : String(err)}`,
        );
      }
    },
    [],
  );

  // --- SSE job events ---
  interface JobEvent {
    id: number;
    status: string;
    job_type: string;
    result: Record<string, unknown> | null;
    last_error: string | null;
  }

  const prevSseStatus = useRef<ConnectionStatus | null>(null);

  const handleJobEvent = useCallback((payload: JobEvent, eventType: string) => {
    if (eventType === "job.archived") return;
    setLegs((prev) => {
      const legIdx = prev.findIndex((l) => l.fetchJobId === payload.id);
      if (legIdx === -1) return prev;
      const leg = prev[legIdx];
      const next = [...prev];
      if (payload.status === "completed") {
        const result = payload.result;
        const snapshot = (result?.snapshot as Record<string, unknown>) ?? {};
        const results =
          (snapshot?.results as Array<Record<string, unknown>>) ?? [];
        const priceData = results[0];
        next[legIdx] = {
          ...leg,
          fetchStatus: "done",
          bid: priceData?.bid != null ? Number(priceData.bid) : leg.bid,
          ask: priceData?.ask != null ? Number(priceData.ask) : leg.ask,
          ivstart: priceData?.iv != null ? Number(priceData.iv) : leg.ivstart,
          undPrice:
            priceData?.und_price != null
              ? Number(priceData.und_price)
              : leg.undPrice,
          tradePrice:
            priceData?.bid != null && priceData?.ask != null
              ? (Number(priceData.bid) + Number(priceData.ask)) / 2
              : leg.tradePrice,
          observedAt: new Date().toISOString(),
        };
      } else if (payload.status === "failed") {
        next[legIdx] = { ...leg, fetchStatus: "error" };
      }
      return next;
    });
  }, []);

  const sseStatus = useSSE<JobEvent>("jobs", handleJobEvent);

  useEffect(() => {
    if (prevSseStatus.current === "disconnected" && sseStatus === "connected") {
      // Re-fetch on reconnect if needed
    }
    prevSseStatus.current = sseStatus;
  }, [sseStatus]);

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
      ivend: leg.ivend,
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
    <div className="flex gap-6">
      {/* Left sidebar — saved structures */}
      <div className="w-56 shrink-0">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Structures
        </h2>
        <div className="space-y-1 mb-3">
          {savedStructures.length === 0 && (
            <p className="text-xs text-gray-400">No saved structures</p>
          )}
          {savedStructures.map((s) => (
            <button
              key={s.id}
              onClick={() => handleLoadStructure(s.id)}
              className={`w-full text-left px-2 py-1.5 rounded text-sm truncate ${
                loadedStructureId === s.id
                  ? "bg-blue-100 text-blue-800 font-medium"
                  : "text-gray-700 hover:bg-gray-100"
              }`}
              title={s.name}
            >
              <span className="text-gray-400 text-xs mr-1">
                /{s.instrument}
              </span>
              {s.name}
            </button>
          ))}
        </div>
        <div className="flex flex-col gap-1">
          <button
            onClick={handleSaveAs}
            className="text-xs border border-blue-500 text-blue-600 rounded px-2 py-1 hover:bg-blue-50"
          >
            Save As...
          </button>
          {loadedStructureId != null && (
            <>
              <button
                onClick={handleSave}
                className="text-xs bg-blue-600 text-white rounded px-2 py-1 hover:bg-blue-700"
              >
                Save
              </button>
              <button
                onClick={handleDeleteStructure}
                className="text-xs border border-red-400 text-red-500 rounded px-2 py-1 hover:bg-red-50"
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
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

        {/* Legs Table — order: # | Type | Expiry | Strike | Qty | IV | IV End | Und | Bid | Ask | Mid | x */}
        <div className="mb-4">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Legs
          </h2>
          <table className="text-sm border border-gray-200 rounded w-full">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-2 py-1.5 w-8"></th>
                <th className="px-2 py-1.5 text-left w-10">#</th>
                <th className="px-2 py-1.5 text-left w-20">Type</th>
                <th className="px-2 py-1.5 text-left w-52">Expiry</th>
                <th className="px-2 py-1.5 text-left w-36">Strike</th>
                <th className="px-2 py-1.5 text-left w-16">Qty</th>
                <th className="px-2 py-1.5 text-left w-20">IV</th>
                <th className="px-2 py-1.5 text-left w-20">IV End</th>
                <th className="px-2 py-1.5 text-left w-20">Und</th>
                <th className="px-2 py-1.5 text-left w-20">Bid</th>
                <th className="px-2 py-1.5 text-left w-20">Ask</th>
                <th className="px-2 py-1.5 text-left w-20">Mid</th>
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
    </div>
  );
}

// --- Leg Row Sub-component ---
// Cascade: Type → Expiry → Strike

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
  availableOptions: ChainEntry[];
  futuresContracts: FuturesContract[];
  optionsLoading: boolean;
  futuresLoading: boolean;
  onUpdate: (id: string, updates: Partial<LegRow>) => void;
  onRemove: (id: string) => void;
  onFetchPrice: (legId: string, entry: ChainEntry) => void;
}) {
  const isD1 = leg.optionType === "d1";
  const isCash = leg.optionType === "cash";
  const isOption = !isD1 && !isCash;
  const mid = midPrice(leg.bid, leg.ask);

  // --- Option cascade: Type → Expiry → Strike ---
  const rightFilter = leg.optionType === "c" ? "C" : "P";
  const optionsForType = isOption
    ? availableOptions.filter((o) => o.right === rightFilter)
    : [];

  // Build unique expiry options (deduplicated by trading_class + expiration)
  const expiryOptions: {
    key: string;
    expiry: string;
    tc: string;
    dte: number;
    isMonthly: boolean;
    label: string;
  }[] = [];
  const seenExpiries = new Set<string>();
  for (const o of optionsForType) {
    const key = `${o.trading_class}-${o.expiration}`;
    if (seenExpiries.has(key)) continue;
    seenExpiries.add(key);
    const expiryLabel = formatExpiration(o.expiration, o.is_monthly);
    const tcLabel = o.is_monthly ? "" : ` [${o.trading_class}]`;
    expiryOptions.push({
      key,
      expiry: o.expiration,
      tc: o.trading_class,
      dte: o.dte,
      isMonthly: o.is_monthly,
      label: `${expiryLabel}${tcLabel} (${o.dte}d)`,
    });
  }
  expiryOptions.sort((a, b) => a.dte - b.dte);

  // Filter strikes by selected expiry
  const optionsForExpiry =
    leg.selectedExpiry && leg.selectedTradingClass
      ? optionsForType.filter(
          (o) =>
            o.expiration === leg.selectedExpiry &&
            o.trading_class === leg.selectedTradingClass,
        )
      : [];

  const uniqueStrikes = [
    ...new Set(optionsForExpiry.map((o) => o.strike)),
  ].sort((a, b) => a - b);
  const strikeComboboxOptions: ComboboxOption<number>[] = uniqueStrikes.map(
    (s) => ({
      label: s.toFixed(2),
      value: String(s),
      data: s,
    }),
  );

  // D1: futures contract selector
  const futuresComboboxOptions: ComboboxOption<FuturesContract>[] =
    futuresContracts.map((f) => ({
      label: `${f.display_name} (DTE ${f.dte})`,
      value: String(f.con_id),
      data: f,
    }));

  // --- Handlers ---
  const hasPricingData = (c: {
    bid: number | null;
    ask: number | null;
    iv?: number | null;
  }) => c.bid != null || c.ask != null || c.iv != null;

  const applyChainEntry = (contract: ChainEntry) => {
    const m = midPrice(contract.bid, contract.ask);
    const hasData = hasPricingData(contract);
    onUpdate(leg.id, {
      selectedConId: contract.con_id,
      strike: contract.strike,
      dte: contract.dte,
      ivstart: contract.iv ?? 0,
      bid: contract.bid,
      ask: contract.ask,
      tradePrice: m,
      undPrice: contract.und_price,
      observedAt: contract.observed_at,
      fetchStatus: hasData ? "done" : "idle",
    });
    if (!hasData) onFetchPrice(leg.id, contract);
  };

  const handleExpirySelect = (key: string) => {
    const opt = expiryOptions.find((e) => e.key === key);
    if (!opt) return;
    // Set expiry, clear strike
    onUpdate(leg.id, {
      selectedExpiry: opt.expiry,
      selectedTradingClass: opt.tc,
      dte: opt.dte,
      strike: null,
      selectedConId: null,
      ivstart: 0,
      bid: null,
      ask: null,
      tradePrice: null,
      undPrice: null,
    });
  };

  const handleStrikeSelect = (option: ComboboxOption<number>) => {
    const strike = option.data;
    // Find the exact chain entry for this expiry+strike
    const match = optionsForExpiry.find((o) => o.strike === strike);
    if (match) {
      applyChainEntry(match);
    } else {
      onUpdate(leg.id, {
        strike,
        selectedConId: null,
        bid: null,
        ask: null,
        tradePrice: null,
      });
    }
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
      onFetchPrice(leg.id, {
        con_id: fut.con_id,
        symbol: fut.symbol,
      } as ChainEntry);
    }
  };

  const handleRefresh = () => {
    // Find the chain entry for this leg's current selection
    if (
      isOption &&
      leg.selectedExpiry &&
      leg.selectedTradingClass &&
      leg.strike != null
    ) {
      const entry = availableOptions.find(
        (o) =>
          o.expiration === leg.selectedExpiry &&
          o.trading_class === leg.selectedTradingClass &&
          o.strike === leg.strike &&
          o.right === (leg.optionType === "c" ? "C" : "P"),
      );
      if (entry)
        onFetchPrice(leg.id, {
          ...entry,
          con_id: leg.selectedConId ?? entry.con_id,
        });
    } else if (isD1 && leg.selectedConId) {
      onFetchPrice(leg.id, {
        con_id: leg.selectedConId,
        symbol: "",
      } as ChainEntry);
    }
  };

  const resetLeg = (newType: LegRow["optionType"]) => {
    onUpdate(leg.id, {
      optionType: newType,
      selectedConId: null,
      contractLabel: "",
      selectedExpiry: null,
      selectedTradingClass: null,
      strike: null,
      dte: 0,
      ivstart: 0,
      ivend: null,
      bid: null,
      ask: null,
      tradePrice: null,
      undPrice: null,
      observedAt: null,
      fetchStatus: "idle",
      fetchJobId: null,
    });
  };

  return (
    <tr className="border-t border-gray-100">
      {/* Remove button */}
      <td className="px-2 py-1.5">
        <button
          onClick={() => onRemove(leg.id)}
          className="text-gray-400 hover:text-red-500 text-xs"
        >
          ✕
        </button>
      </td>
      {/* # with status dot + refresh */}
      <td className="px-2 py-1.5 text-gray-400">
        <div className="flex items-center gap-1">
          {leg.fetchStatus === "working" && (
            <span
              className="inline-block w-2 h-2 rounded-full bg-yellow-400 animate-pulse"
              title="Qualifying & fetching..."
            />
          )}
          {leg.fetchStatus === "done" && (
            <span
              className="inline-block w-2 h-2 rounded-full bg-green-500"
              title={
                leg.observedAt
                  ? `Fetched: ${new Date(leg.observedAt).toLocaleTimeString()}`
                  : "Data loaded"
              }
            />
          )}
          {leg.fetchStatus === "error" && (
            <span
              className="inline-block w-2 h-2 rounded-full bg-red-500"
              title="Error fetching data"
            />
          )}
          {index + 1}
          {(leg.fetchStatus === "done" || leg.fetchStatus === "error") && (
            <button
              onClick={handleRefresh}
              disabled={leg.fetchStatus === "working"}
              className="ml-1 rounded border border-gray-300 px-1.5 py-0.5 text-[11px] text-gray-600 hover:bg-gray-50 hover:text-blue-600"
              title="Refresh pricing data"
            >
              Refresh
            </button>
          )}
        </div>
        {leg.fetchStatus === "done" && leg.observedAt && (
          <div className="text-[10px] text-gray-400 leading-tight">
            {new Date(leg.observedAt).toLocaleTimeString()}
          </div>
        )}
      </td>
      {/* Type */}
      <td className="px-2 py-1.5">
        <select
          value={leg.optionType}
          onChange={(e) => resetLeg(e.target.value as LegRow["optionType"])}
          className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
        >
          <option value="c">Call</option>
          <option value="p">Put</option>
          <option value="d1">D1</option>
          <option value="cash">Cash</option>
        </select>
      </td>
      {/* Expiry (was DTE — now comes before Strike) */}
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
            step="1"
            value={leg.dte || ""}
            onChange={(e) =>
              onUpdate(leg.id, { dte: parseInt(e.target.value) || 0 })
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
            placeholder="DTE"
          />
        ) : (
          <select
            value={
              leg.selectedExpiry && leg.selectedTradingClass
                ? `${leg.selectedTradingClass}-${leg.selectedExpiry}`
                : ""
            }
            onChange={(e) =>
              e.target.value ? handleExpirySelect(e.target.value) : undefined
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
          >
            <option value="">
              {optionsLoading ? "Loading..." : "Select expiry..."}
            </option>
            {expiryOptions.map((e) => (
              <option key={e.key} value={e.key}>
                {e.label}
              </option>
            ))}
          </select>
        )}
      </td>
      {/* Strike (filtered by selected expiry) */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <span className="text-gray-500 text-sm">
            {leg.dte ? `${leg.dte}d` : "—"}
          </span>
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
        ) : !leg.selectedExpiry ? (
          <span className="text-gray-400 text-xs">Pick expiry first</span>
        ) : (
          <ComboboxInput
            options={strikeComboboxOptions}
            value={leg.strike != null ? leg.strike.toFixed(2) : ""}
            onChange={handleStrikeSelect}
            onClear={() =>
              onUpdate(leg.id, {
                strike: null,
                selectedConId: null,
                ivstart: 0,
                bid: null,
                ask: null,
                tradePrice: null,
                undPrice: null,
              })
            }
            placeholder="Strike..."
            loading={false}
          />
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
      {/* IV End */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <span className="text-gray-400">—</span>
        ) : (
          <input
            type="number"
            step="any"
            value={leg.ivend ?? ""}
            onChange={(e) =>
              onUpdate(leg.id, {
                ivend: e.target.value ? parseFloat(e.target.value) : null,
              })
            }
            className="border border-gray-300 rounded px-1 py-0.5 text-sm w-full"
          />
        )}
      </td>
      {/* Und */}
      <td className="px-2 py-1.5 text-gray-500">
        {leg.undPrice?.toFixed(2) ?? "—"}
      </td>
      {/* Bid / Ask / Mid */}
      <td className="px-2 py-1.5 text-gray-500">
        {leg.bid?.toFixed(2) ?? "—"}
      </td>
      <td className="px-2 py-1.5 text-gray-500">
        {leg.ask?.toFixed(2) ?? "—"}
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
