// The sync buttons on the right of the Trades header: intraday TWS, the
// FlexQuery windows, since-last-trade, and an explicit date range, with the
// queued/failed message anchored under them.

import { useState } from "react";
import type { TradeSync } from "./useTradeSync";

const SYNC_BUTTON =
  "whitespace-nowrap rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50";

export default function TradesSyncControls({ sync }: { sync: TradeSync }) {
  const [rangeStart, setRangeStart] = useState("");
  const [rangeEnd, setRangeEnd] = useState("");
  const { syncing } = sync;
  const busyOr = (label: string) => (syncing ? "Queueing..." : label);

  return (
    <div className="relative flex flex-col items-end gap-2">
      <div className="flex flex-nowrap items-center gap-2">
        <span className="whitespace-nowrap text-xs font-semibold text-gray-700">
          Sync
        </span>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffIntradaySync();
          }}
          disabled={syncing}
          title="Pull today's live fills, marks, and positions directly from TWS (does not hit FlexQuery)"
          className="whitespace-nowrap rounded border border-emerald-300 px-3 py-1 text-sm text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          {busyOr("Intraday (TWS)")}
        </button>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("Quick sync", { days: 1 });
          }}
          disabled={syncing}
          className={SYNC_BUTTON}
        >
          {busyOr("1 Day")}
        </button>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("3 day sync", { days: 3 });
          }}
          disabled={syncing}
          className={SYNC_BUTTON}
        >
          {busyOr("3 Days")}
        </button>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("Full sync", { days: 7 });
          }}
          disabled={syncing}
          className={SYNC_BUTTON}
        >
          {busyOr("7 Days")}
        </button>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("Extended sync", { days: 30 });
          }}
          disabled={syncing}
          className={SYNC_BUTTON}
        >
          {busyOr("30 Days")}
        </button>
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("Sync since last trade", {
              sinceLastTrade: true,
            });
          }}
          disabled={syncing}
          title="Sync from the most recent trade date across all accounts through today"
          className={SYNC_BUTTON}
        >
          {busyOr("Since Last Trade")}
        </button>
      </div>
      <div className="flex flex-nowrap items-center gap-2">
        <span className="whitespace-nowrap text-xs font-medium text-gray-500">
          Custom range:
        </span>
        <input
          type="date"
          value={rangeStart}
          onChange={(event) => setRangeStart(event.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-700"
          aria-label="Sync start date"
        />
        <span className="text-xs text-gray-400">→</span>
        <input
          type="date"
          value={rangeEnd}
          onChange={(event) => setRangeEnd(event.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm text-gray-700"
          aria-label="Sync end date"
        />
        <button
          type="button"
          onClick={() => {
            void sync.kickOffTradesSync("Range sync", {
              startDate: rangeStart,
              endDate: rangeEnd,
            });
          }}
          disabled={
            syncing || !rangeStart || !rangeEnd || rangeStart > rangeEnd
          }
          title="Sync trades for an explicit date range (FlexQuery is T-1, so the end date must be the previous business day or earlier)"
          className={SYNC_BUTTON}
        >
          {busyOr("Sync")}
        </button>
      </div>
      {(sync.message || sync.error) && (
        <div className="absolute right-0 top-full mt-1 max-w-md">
          {sync.message && (
            <p className="text-right text-sm text-green-700">{sync.message}</p>
          )}
          {sync.error && (
            <p className="text-right text-sm text-red-600">
              Sync error: {sync.error}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
