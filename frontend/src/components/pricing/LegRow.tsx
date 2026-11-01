// One leg of the structure: remove, status and refresh, type, the expiry and
// strike cascade, quantity, IVs, and the quote columns.

import {
  chainRight,
  formatQuantityInput,
  midPrice,
  parseQuantityInput,
  resetLegFields,
  type LegRow as LegRowData,
} from "../../lib/pricing/legs";
import type {
  ChainEntry,
  FuturesContract,
  LegType,
} from "../../types/pricing";
import LegOptionCascade from "./LegOptionCascade";

const FIELD = "border border-gray-300 rounded px-1 py-0.5 text-sm w-full";

export default function LegRow({
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
  leg: LegRowData;
  index: number;
  availableOptions: ChainEntry[];
  futuresContracts: FuturesContract[];
  optionsLoading: boolean;
  futuresLoading: boolean;
  onUpdate: (id: string, updates: Partial<LegRowData>) => void;
  onRemove: (id: string) => void;
  onFetchPrice: (legId: string, entry: ChainEntry) => void;
}) {
  const isD1 = leg.optionType === "d1";
  const isCash = leg.optionType === "cash";
  const isOption = !isD1 && !isCash;
  const mid = midPrice(leg.bid, leg.ask);
  const canRefreshOption =
    isOption &&
    leg.selectedExpiry != null &&
    leg.selectedTradingClass != null &&
    leg.strike != null;
  const showRefreshButton =
    isOption || leg.fetchStatus === "done" || leg.fetchStatus === "error";
  const optionsForType = isOption
    ? availableOptions.filter((o) => o.right === chainRight(leg.optionType))
    : [];

  const update = (updates: Partial<LegRowData>) => onUpdate(leg.id, updates);

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
          o.right === chainRight(leg.optionType),
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

  const handleQuantityChange = (value: string) => {
    const parsedQuantity = parseQuantityInput(value);
    update({
      quantityInput: value,
      ...(parsedQuantity != null ? { quantity: parsedQuantity } : {}),
    });
  };

  const handleQuantityBlur = () => {
    const parsedQuantity = parseQuantityInput(leg.quantityInput);
    update({
      quantity: parsedQuantity ?? leg.quantity,
      quantityInput:
        parsedQuantity != null
          ? formatQuantityInput(parsedQuantity)
          : formatQuantityInput(leg.quantity),
    });
  };

  return (
    <tr className="border-t border-gray-100">
      {/* Remove button */}
      <td className="px-2 py-1.5">
        <button
          type="button"
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
          {showRefreshButton && (
            <button
              type="button"
              onClick={handleRefresh}
              disabled={
                leg.fetchStatus === "working" || (isOption && !canRefreshOption)
              }
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
          onChange={(e) =>
            update(resetLegFields(leg, e.target.value as LegType))
          }
          className={FIELD}
        >
          <option value="c">Call</option>
          <option value="p">Put</option>
          <option value="d1">D1</option>
          <option value="cash">Cash</option>
        </select>
      </td>
      <LegOptionCascade
        leg={leg}
        optionsForType={optionsForType}
        futuresContracts={futuresContracts}
        optionsLoading={optionsLoading}
        futuresLoading={futuresLoading}
        onUpdate={update}
        onFetchPrice={(entry) => onFetchPrice(leg.id, entry)}
      />
      {/* Qty */}
      <td className="px-2 py-1.5">
        <input
          type="text"
          inputMode="decimal"
          value={leg.quantityInput}
          onChange={(e) => handleQuantityChange(e.target.value)}
          onBlur={handleQuantityBlur}
          className={FIELD}
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
              update({ ivstart: parseFloat(e.target.value) || 0 })
            }
            className={FIELD}
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
              update({
                ivend: e.target.value ? parseFloat(e.target.value) : null,
              })
            }
            className={FIELD}
          />
        )}
      </td>
      {/* Und */}
      <td className="px-2 py-1.5 text-gray-500">
        {leg.undPrice?.toFixed(2) ?? "—"}
      </td>
      {/* Bid / Ask / Mid */}
      <td className="px-2 py-1.5 text-gray-500">{leg.bid?.toFixed(2) ?? "—"}</td>
      <td className="px-2 py-1.5 text-gray-500">{leg.ask?.toFixed(2) ?? "—"}</td>
      <td className="px-2 py-1.5">
        <input
          type="number"
          step="any"
          value={leg.tradePrice ?? mid ?? ""}
          onChange={(e) =>
            update({
              tradePrice: e.target.value ? parseFloat(e.target.value) : null,
            })
          }
          className={FIELD}
        />
      </td>
      <td className="px-2 py-1.5 text-gray-500">
        {leg.volume != null ? leg.volume.toLocaleString() : "—"}
      </td>
      <td className="px-2 py-1.5 text-gray-500">
        {leg.openInterest != null ? leg.openInterest.toLocaleString() : "—"}
      </td>
      <td className="px-2 py-1.5 font-mono text-xs text-gray-500">
        {leg.selectedConId ?? "—"}
      </td>
    </tr>
  );
}
