// Title row, P&L totals, the three sync buttons, the greeks toggle, the
// account chips, and the status lines above the table.

import { formatMarkTime } from "../../lib/markTime";
import type { PositionTotals } from "../../lib/positions/view";
import { formatRelativeReturn } from "../../utils/privacy";
import type { PositionSync } from "./usePositionSync";
import { OUTLINE_BUTTON } from "../ui/buttonClasses";

function pnlClass(value: number | null): string {
  if (value == null) return "text-gray-500";
  return value >= 0
    ? "font-semibold text-emerald-700"
    : "font-semibold text-red-700";
}

function pnlText(
  value: number | null,
  costBasis: number | null,
  privacyMode: boolean,
): string {
  if (privacyMode) return formatRelativeReturn(value, costBasis);
  if (value == null) return "—";
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
  });
}

export default function PositionsToolbar({
  totals,
  privacyMode,
  sync,
  showGreeks,
  onToggleGreeks,
  onClearFilters,
  accountAliases,
  accountFilter,
  onAccountFilter,
  assignError,
}: {
  totals: PositionTotals;
  privacyMode: boolean;
  sync: PositionSync;
  showGreeks: boolean;
  onToggleGreeks: () => void;
  onClearFilters: () => void;
  accountAliases: string[];
  accountFilter: string;
  onAccountFilter: (alias: string) => void;
  assignError: string | null;
}) {
  return (
    <>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-gray-900">Positions</h2>
          <button
            type="button"
            onClick={onClearFilters}
            className="rounded border border-gray-300 px-3 py-1 text-sm text-gray-700 hover:bg-gray-50"
          >
            Clear Filters
          </button>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-600">
            Unrealized PnL:{" "}
            <span className={pnlClass(totals.unrealized)}>
              {pnlText(totals.unrealized, totals.costBasis, privacyMode)}
            </span>
          </span>
          <span className="text-sm text-gray-600">
            Live PnL:{" "}
            <span className={pnlClass(totals.liveUnrealized)}>
              {pnlText(totals.liveUnrealized, totals.costBasis, privacyMode)}
            </span>
            {totals.newestMarkTs && (
              <span className="ml-1 text-xs text-gray-400">
                (live as of {formatMarkTime(totals.newestMarkTs)})
              </span>
            )}
          </span>
          <button
            type="button"
            onClick={() => {
              void sync.kickOff("flex");
            }}
            disabled={sync.busy.flex}
            className={OUTLINE_BUTTON}
          >
            {sync.busy.flex ? "Queueing..." : "Kick Off Position Sync"}
          </button>
          <button
            type="button"
            onClick={() => {
              void sync.kickOff("intraday");
            }}
            disabled={sync.busy.intraday}
            className="rounded border border-emerald-300 px-3 py-1 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
          >
            {sync.busy.intraday ? "Queueing..." : "Refresh Live (TWS)"}
          </button>
          <button
            type="button"
            onClick={() => {
              void sync.kickOff("metrics");
            }}
            disabled={sync.busy.metrics}
            className="rounded border border-violet-300 px-3 py-1 text-sm text-violet-700 hover:bg-violet-50 disabled:opacity-50"
          >
            {sync.busy.metrics ? "Queueing..." : "Refresh Metrics (TWS)"}
          </button>
          <button
            type="button"
            onClick={onToggleGreeks}
            aria-pressed={showGreeks}
            className={`rounded border px-3 py-1 text-sm ${
              showGreeks
                ? "border-violet-400 bg-violet-50 text-violet-700"
                : "border-gray-300 text-gray-700 hover:bg-gray-50"
            }`}
          >
            {showGreeks ? "Hide greeks" : "Show greeks"}
          </button>
        </div>
      </div>

      {accountAliases.length > 1 && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => onAccountFilter("all")}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              accountFilter === "all"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All
          </button>
          {accountAliases.map((alias) => (
            <button
              key={alias}
              type="button"
              onClick={() => onAccountFilter(alias)}
              className={`rounded px-2.5 py-1 text-xs font-medium tracking-wide ${
                accountFilter === alias
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {alias}
            </button>
          ))}
        </div>
      )}

      {sync.message && <p className="text-sm text-green-700">{sync.message}</p>}
      {sync.error && (
        <p className="text-sm text-red-600">Sync error: {sync.error}</p>
      )}
      {assignError && (
        <p className="text-sm text-red-600">
          Trade group assignment error: {assignError}
        </p>
      )}
    </>
  );
}
