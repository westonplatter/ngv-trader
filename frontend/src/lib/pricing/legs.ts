// Pure leg logic behind the Pricing page: the leg row shape, conversions to
// and from saved structures and the pricing API, the option cascade (type →
// expiry → strike), quote-fetch job payloads, and folding a finished job back
// into its leg.
//
// Kept out of the components so the behavior has a bun test: the repo has no
// DOM harness, so anything worth asserting must be a function over plain data.

import type { WatchedJob } from "../../hooks/useJobWatcher";
import type {
  ChainEntry,
  FuturesContract,
  LegType,
  SavedLeg,
} from "../../types/pricing";

export type FetchStatus = "idle" | "working" | "done" | "error";

// One row of the legs table: the selection plus the quote it carries.
export interface LegRow {
  id: string;
  optionType: LegType;
  selectedConId: number | null;
  contractLabel: string;
  selectedExpiry: string | null;
  selectedTradingClass: string | null;
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  // What the operator typed; `quantity` is the last parseable value of it.
  quantityInput: string;
  tradePrice: number | null;
  bid: number | null;
  ask: number | null;
  undPrice: number | null;
  volume: number | null;
  openInterest: number | null;
  observedAt: string | null;
  fetchStatus: FetchStatus;
  fetchJobId: number | null;
}

export function createEmptyLeg(): LegRow {
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
    quantityInput: "1",
    tradePrice: null,
    bid: null,
    ask: null,
    undPrice: null,
    volume: null,
    openInterest: null,
    observedAt: null,
    fetchStatus: "idle",
    fetchJobId: null,
  };
}

// The fields a type change resets, keeping only the id and the quantity.
export function resetLegFields(leg: LegRow, newType: LegType): Partial<LegRow> {
  return {
    optionType: newType,
    selectedConId: null,
    contractLabel: "",
    selectedExpiry: null,
    selectedTradingClass: null,
    strike: null,
    dte: 0,
    ivstart: 0,
    ivend: null,
    quantityInput: formatQuantityInput(leg.quantity),
    bid: null,
    ask: null,
    tradePrice: null,
    undPrice: null,
    volume: null,
    openInterest: null,
    observedAt: null,
    fetchStatus: "idle",
    fetchJobId: null,
  };
}

export function midPrice(bid: number | null, ask: number | null): number | null {
  if (bid != null && ask != null) return (bid + ask) / 2;
  return bid ?? ask ?? null;
}

export function formatQuantityInput(quantity: number): string {
  return Number.isFinite(quantity) ? String(quantity) : "";
}

// Blank means zero (a leg being cleared); anything non-numeric is rejected.
export function parseQuantityInput(value: string): number | null {
  const trimmed = value.trim();
  if (trimmed === "") return 0;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

// A quote has data when any of bid, ask, or IV is present.
export function hasPricingData(c: {
  bid: number | null;
  ask: number | null;
  iv?: number | null;
}): boolean {
  return c.bid != null || c.ask != null || c.iv != null;
}

// Spot inputs seeded from a price: the spot itself and a ±20% window.
export function spotRange(price: number): {
  spot: string;
  min: string;
  max: string;
} {
  return {
    spot: price.toFixed(2),
    min: (price * 0.8).toFixed(2),
    max: (price * 1.2).toFixed(2),
  };
}

// ─── Saved structures ────────────────────────────────────────────────────────

export function legsToSaved(legs: LegRow[]): SavedLeg[] {
  return legs.map((leg) => ({
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

export function savedLegsToRows(savedLegs: SavedLeg[]): LegRow[] {
  return savedLegs.map((sl) => ({
    id: crypto.randomUUID(),
    optionType: sl.optionType,
    strike: sl.strike,
    dte: sl.dte,
    ivstart: sl.ivstart,
    ivend: sl.ivend ?? null,
    quantity: sl.quantity,
    quantityInput: formatQuantityInput(sl.quantity),
    tradePrice: sl.tradePrice,
    bid: sl.bid,
    ask: sl.ask,
    undPrice: sl.undPrice,
    volume: null,
    openInterest: null,
    contractLabel: sl.contractLabel,
    selectedConId: sl.selectedConId,
    selectedExpiry: sl.selectedExpiry ?? null,
    selectedTradingClass: sl.selectedTradingClass ?? null,
    observedAt: null,
    fetchStatus: "idle",
    fetchJobId: null,
  }));
}

// ─── Pricing API ─────────────────────────────────────────────────────────────

export interface ApiLeg {
  option_type: LegType;
  strike: number | null;
  dte: number;
  ivstart: number;
  ivend: number | null;
  quantity: number;
  trade_price: number | null;
  rate: null;
  underlying: null;
}

export function legsToApi(legs: LegRow[]): ApiLeg[] {
  return legs.map((leg) => ({
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
}

// ─── Option cascade ──────────────────────────────────────────────────────────

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

// YYYYMMDD as "Mar 2027" for a monthly, "19-Mar-2027" for a weekly.
export function formatExpiration(expiration: string, isMonthly: boolean): string {
  if (expiration.length !== 8) return expiration;
  const y = parseInt(expiration.slice(0, 4));
  const m = parseInt(expiration.slice(4, 6)) - 1;
  const d = parseInt(expiration.slice(6, 8));
  if (isMonthly) return `${MONTHS[m]} ${y}`;
  return `${String(d).padStart(2, "0")}-${MONTHS[m]}-${y}`;
}

export function chainRight(optionType: LegType): "C" | "P" {
  return optionType === "c" ? "C" : "P";
}

export interface ExpiryOption {
  key: string;
  expiry: string;
  tc: string;
  dte: number;
  isMonthly: boolean;
  label: string;
}

// Unique expiries for one right (deduplicated by trading_class + expiration),
// nearest first. Weeklies carry their trading class in the label.
export function expiryOptions(optionsForType: ChainEntry[]): ExpiryOption[] {
  const result: ExpiryOption[] = [];
  const seen = new Set<string>();
  for (const o of optionsForType) {
    const key = `${o.trading_class}-${o.expiration}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const expiryLabel = formatExpiration(o.expiration, o.is_monthly);
    const tcLabel = o.is_monthly ? "" : ` [${o.trading_class}]`;
    result.push({
      key,
      expiry: o.expiration,
      tc: o.trading_class,
      dte: o.dte,
      isMonthly: o.is_monthly,
      label: `${expiryLabel}${tcLabel} (${o.dte}d)`,
    });
  }
  result.sort((a, b) => a.dte - b.dte);
  return result;
}

// Chain entries of one right at the selected expiry and trading class.
export function entriesForExpiry(
  optionsForType: ChainEntry[],
  expiry: string | null,
  tradingClass: string | null,
): ChainEntry[] {
  if (!expiry || !tradingClass) return [];
  return optionsForType.filter(
    (o) => o.expiration === expiry && o.trading_class === tradingClass,
  );
}

export function uniqueStrikes(entries: ChainEntry[]): number[] {
  return [...new Set(entries.map((o) => o.strike))].sort((a, b) => a - b);
}

// ─── Quote fetch jobs ────────────────────────────────────────────────────────

// A known contract id takes the cheap snapshot job; otherwise the contract
// has to be qualified first.
export function priceJobPayload(entry: ChainEntry): Record<string, unknown> {
  return entry.con_id != null
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
}

// The leg fields a selected chain entry fills in.
export function legFromChainEntry(contract: ChainEntry): Partial<LegRow> {
  return {
    selectedConId: contract.con_id,
    strike: contract.strike,
    dte: contract.dte,
    ivstart: contract.iv ?? 0,
    bid: contract.bid,
    ask: contract.ask,
    tradePrice: midPrice(contract.bid, contract.ask),
    undPrice: contract.und_price,
    volume: null,
    openInterest: null,
    observedAt: contract.observed_at,
    fetchStatus: hasPricingData(contract) ? "done" : "idle",
  };
}

// The leg fields a selected futures contract (a D1 leg) fills in.
export function legFromFuture(fut: FuturesContract): Partial<LegRow> {
  return {
    selectedConId: fut.con_id,
    contractLabel: fut.display_name,
    strike: null,
    dte: fut.dte,
    ivstart: 0,
    bid: fut.bid,
    ask: fut.ask,
    tradePrice: midPrice(fut.bid, fut.ask),
    undPrice: fut.last ?? fut.close ?? 0,
    volume: fut.volume,
    openInterest: fut.open_interest,
  };
}

// Fold a finished price-fetch job into the leg that asked for it. A completed
// snapshot fills the quote fields; a failed job marks the leg.
export function applyPriceJobResult(
  prev: LegRow[],
  legId: string,
  job: WatchedJob,
  now: () => string = () => new Date().toISOString(),
): LegRow[] {
  const legIdx = prev.findIndex((l) => l.id === legId);
  if (legIdx === -1) return prev;
  const leg = prev[legIdx];
  const next = [...prev];
  if (job.status === "completed") {
    const result = job.result;
    const snapshot = (result?.snapshot as Record<string, unknown>) ?? {};
    const results = Array.isArray(result?.results)
      ? (result.results as Array<Record<string, unknown>>)
      : ((snapshot?.results as Array<Record<string, unknown>>) ?? []);
    const priceData = results[0];
    next[legIdx] = {
      ...leg,
      fetchStatus: "done",
      selectedConId:
        priceData?.con_id != null
          ? Number(priceData.con_id)
          : leg.selectedConId,
      bid: priceData?.bid != null ? Number(priceData.bid) : leg.bid,
      ask: priceData?.ask != null ? Number(priceData.ask) : leg.ask,
      ivstart: priceData?.iv != null ? Number(priceData.iv) : leg.ivstart,
      undPrice:
        priceData?.und_price != null
          ? Number(priceData.und_price)
          : leg.undPrice,
      volume: priceData?.volume != null ? Number(priceData.volume) : leg.volume,
      openInterest:
        priceData?.open_interest != null
          ? Number(priceData.open_interest)
          : leg.openInterest,
      tradePrice:
        priceData?.bid != null && priceData?.ask != null
          ? (Number(priceData.bid) + Number(priceData.ask)) / 2
          : leg.tradePrice,
      observedAt: now(),
    };
  } else if (job.status === "failed") {
    next[legIdx] = { ...leg, fetchStatus: "error" };
  }
  return next;
}
