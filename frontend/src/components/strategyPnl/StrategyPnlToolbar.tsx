// The title row with the live-refresh button, and the account / instrument /
// status filters with the loading note.

import type { IntradayRefresh } from "./useIntradayRefresh";
import type { StrategyPnlRows } from "./useStrategyPnlRows";

const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

export default function StrategyPnlToolbar({
  data,
  refresh,
}: {
  data: StrategyPnlRows;
  refresh: IntradayRefresh;
}) {
  return (
    <>
      <div className="flex flex-wrap items-end gap-3">
        <h2 className="mr-auto text-base font-semibold text-gray-800">
          Strategy P&amp;L
        </h2>
        <button
          type="button"
          onClick={() => void refresh.kickOff()}
          disabled={refresh.syncing}
          className="rounded border border-emerald-300 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          {refresh.syncing ? "Queueing…" : "Refresh Live (TWS)"}
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Account
          <select
            value={data.accountId}
            onChange={(e) => data.setAccountId(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            <option value="all">All accounts</option>
            {data.accounts.map((account) => (
              <option key={account.id} value={String(account.id)}>
                {account.alias ?? account.masked_account}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Instrument
          <input
            value={data.instrumentInput}
            onChange={(e) => data.setInstrumentInput(e.target.value)}
            placeholder="CL.*"
            className="w-40 rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Status
          <select
            value={data.status}
            onChange={(e) => data.setStatus(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {data.loading && (
          <span className="pb-1 text-xs text-gray-400">Loading…</span>
        )}
      </div>
    </>
  );
}
