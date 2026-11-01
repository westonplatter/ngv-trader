// The Expiry and Strike cells of a leg row. For an option they cascade
// (type → expiry → strike) over the chain catalog; a D1 leg picks a futures
// contract instead; a cash leg takes a manual DTE and strike.

import type { ComboboxOption } from "../ComboboxInput";
import ComboboxInput from "../ComboboxInput";
import {
  entriesForExpiry,
  expiryOptions,
  hasPricingData,
  legFromChainEntry,
  legFromFuture,
  uniqueStrikes,
  type LegRow,
} from "../../lib/pricing/legs";
import type { ChainEntry, FuturesContract } from "../../types/pricing";

const FIELD = "border border-gray-300 rounded px-1 py-0.5 text-sm w-full";

export default function LegOptionCascade({
  leg,
  optionsForType,
  futuresContracts,
  optionsLoading,
  futuresLoading,
  onUpdate,
  onFetchPrice,
}: {
  leg: LegRow;
  // Chain entries matching the leg's right; empty for D1 and cash legs.
  optionsForType: ChainEntry[];
  futuresContracts: FuturesContract[];
  optionsLoading: boolean;
  futuresLoading: boolean;
  onUpdate: (updates: Partial<LegRow>) => void;
  onFetchPrice: (entry: ChainEntry) => void;
}) {
  const isD1 = leg.optionType === "d1";
  const isCash = leg.optionType === "cash";

  const expiries = expiryOptions(optionsForType);
  const entriesAtExpiry = entriesForExpiry(
    optionsForType,
    leg.selectedExpiry,
    leg.selectedTradingClass,
  );
  const strikeComboboxOptions: ComboboxOption<number>[] = uniqueStrikes(
    entriesAtExpiry,
  ).map((s) => ({ label: s.toFixed(2), value: String(s), data: s }));
  const futuresComboboxOptions: ComboboxOption<FuturesContract>[] =
    futuresContracts.map((f) => ({
      label: `${f.display_name} (DTE ${f.dte})`,
      value: String(f.con_id),
      data: f,
    }));

  const handleExpirySelect = (key: string) => {
    const opt = expiries.find((e) => e.key === key);
    if (!opt) return;
    // Set expiry, clear strike
    onUpdate({
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
      volume: null,
      openInterest: null,
    });
  };

  const handleStrikeSelect = (option: ComboboxOption<number>) => {
    const strike = option.data;
    // Find the exact chain entry for this expiry+strike
    const match = entriesAtExpiry.find((o) => o.strike === strike);
    if (match) {
      onUpdate(legFromChainEntry(match));
      if (!hasPricingData(match)) onFetchPrice(match);
    } else {
      onUpdate({
        strike,
        selectedConId: null,
        bid: null,
        ask: null,
        tradePrice: null,
        volume: null,
        openInterest: null,
      });
    }
  };

  const handleFuturesSelect = (option: ComboboxOption<FuturesContract>) => {
    const fut = option.data;
    onUpdate(legFromFuture(fut));
    if (!hasPricingData(fut)) {
      onFetchPrice({ con_id: fut.con_id, symbol: fut.symbol } as ChainEntry);
    }
  };

  return (
    <>
      {/* Expiry (was DTE — now comes before Strike) */}
      <td className="px-2 py-1.5">
        {isD1 ? (
          <ComboboxInput
            options={futuresComboboxOptions}
            value={leg.contractLabel}
            onChange={handleFuturesSelect}
            onClear={() =>
              onUpdate({
                selectedConId: null,
                contractLabel: "",
                dte: 0,
                bid: null,
                ask: null,
                tradePrice: null,
                undPrice: null,
                volume: null,
                openInterest: null,
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
            onChange={(e) => onUpdate({ dte: parseInt(e.target.value) || 0 })}
            className={FIELD}
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
            className={FIELD}
          >
            <option value="">
              {optionsLoading ? "Loading..." : "Select expiry..."}
            </option>
            {expiries.map((e) => (
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
              onUpdate({
                strike: e.target.value ? parseFloat(e.target.value) : null,
              })
            }
            className={FIELD}
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
              onUpdate({
                strike: null,
                selectedConId: null,
                ivstart: 0,
                bid: null,
                ask: null,
                tradePrice: null,
                undPrice: null,
                volume: null,
                openInterest: null,
              })
            }
            placeholder="Strike..."
            loading={false}
          />
        )}
      </td>
    </>
  );
}
