// Strategy P&L — one row per trade group, with its strategy and P&L split.
//
// Sibling to the three-column Strategies workspace (`TradeTaggingPage`), which
// answers "how is this group doing"; this answers "how is the book doing".
// Read-only by design: assignment, renaming, and status changes stay on the
// workspace page.
//
// All the logic worth asserting lives in ../lib/strategyPnl so it can be tested
// without a DOM.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API_BASE_URL } from "../config";
import { usePrivacy } from "../contexts/usePrivacy";
import {
  DEFAULT_SORT,
  EMPTY_CELL,
  type SortColumn,
  type SortState,
  ariaSort,
  buildTradeGroupsQuery,
  formatFreshness,
  formatInstruments,
  nextSortState,
  resolvePnl,
  sortIndicator,
  sortRows,
  strategyLabel,
} from "../lib/strategyPnl";
import type { TradeGroupPnlRow } from "../lib/tradeGroups";
import { formatMoney } from "../utils/number";
import { PRIVACY_MASK } from "../utils/privacy";

interface AccountOption {
  id: number;
  alias: string | null;
  masked_account: string;
}

const STATUS_OPTIONS = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "All" },
];

const FRESHNESS_CLASS: Record<string, string> = {
  live: "text-emerald-700",
  stale: "text-amber-600",
  none: "text-gray-400",
};

function pnlClass(value: number | null): string {
  if (value == null || value === 0) return "text-gray-700";
  return value > 0 ? "text-emerald-700" : "text-red-600";
}

export default function StrategyPnlTable() {
  const navigate = useNavigate();
  const { privacyMode } = usePrivacy();

  const [status, setStatus] = useState("open");
  const [accountId, setAccountId] = useState("all");
  const [instrumentInput, setInstrumentInput] = useState("");
  const [instrument, setInstrument] = useState("");
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);

  const [rows, setRows] = useState<TradeGroupPnlRow[]>([]);
  const [accounts, setAccounts] = useState<AccountOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);

  // Debounce the pattern input: every keystroke of "CL.*" is otherwise a request,
  // and the intermediate "CL[" would 400.
  useEffect(() => {
    const handle = window.setTimeout(() => setInstrument(instrumentInput), 350);
    return () => window.clearTimeout(handle);
  }, [instrumentInput]);

  const query = useMemo(
    () => buildTradeGroupsQuery({ status, accountId, instrument }),
    [status, accountId, instrument],
  );

  const requestId = useRef(0);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/trade-groups?${query}`);
      if (!res.ok) {
        // A malformed instrument pattern comes back as a 400 with a readable
        // message; surface it rather than an opaque status code.
        let detail = `HTTP ${res.status}`;
        try {
          const body = (await res.json()) as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          /* non-JSON error body — keep the status line */
        }
        throw new Error(detail);
      }
      const data = (await res.json()) as TradeGroupPnlRow[];
      if (id !== requestId.current) return; // a newer request already answered
      setRows(data);
      setError(null);
    } catch (err: unknown) {
      if (id !== requestId.current) return;
      setRows([]);
      setError(
        err instanceof Error ? err.message : "Failed to load trade groups.",
      );
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    // Run through an async wrapper so `load`'s opening setLoading(true) lands
    // after the effect body rather than synchronously inside it — same shape as
    // the accounts effect below.
    void (async () => {
      await load();
    })();
  }, [load]);

  useEffect(() => {
    void (async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/accounts`);
        if (!res.ok) return;
        setAccounts((await res.json()) as AccountOption[]);
      } catch {
        /* the account filter degrades to "All accounts" */
      }
    })();
  }, []);

  const kickOffIntradaySync = async () => {
    setSyncing(true);
    setSyncMessage(null);
    try {
      const res = await fetch(`${API_BASE_URL}/positions/sync/intraday-tws`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source: "manual-ui",
          request_text:
            "Refresh live intraday overlay from the Strategy P&L table.",
          max_attempts: 3,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { job_id: number; status: string };
      setSyncMessage(
        `Queued intraday TWS sync job #${data.job_id} (${data.status}). Refreshing shortly…`,
      );
      // TWS session + reqTickers take longer than a flex enqueue; poll twice.
      window.setTimeout(() => void load(), 3000);
      window.setTimeout(() => void load(), 8000);
    } catch (err: unknown) {
      setSyncMessage(
        err instanceof Error ? err.message : "Failed to queue sync.",
      );
    } finally {
      setSyncing(false);
    }
  };

  const sorted = useMemo(() => sortRows(rows, sort), [rows, sort]);
  const filtersActive =
    status !== "open" || accountId !== "all" || instrument.trim() !== "";

  const money = (value: number | null) =>
    privacyMode ? PRIVACY_MASK : formatMoney(value);

  const header = (
    column: SortColumn,
    label: string,
    align: "left" | "right" = "right",
  ) => (
    <th
      scope="col"
      aria-sort={ariaSort(sort, column)}
      className={`px-3 py-2 font-semibold text-gray-600 text-${align}`}
    >
      <button
        type="button"
        onClick={() => setSort((prev) => nextSortState(prev, column))}
        className="inline-flex items-center gap-1 hover:text-gray-900"
      >
        {label}
        <span className="text-gray-400">{sortIndicator(sort, column)}</span>
      </button>
    </th>
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <h2 className="mr-auto text-base font-semibold text-gray-800">
          Strategy P&amp;L
        </h2>
        <button
          type="button"
          onClick={() => void kickOffIntradaySync()}
          disabled={syncing}
          className="rounded border border-emerald-300 px-3 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-50"
        >
          {syncing ? "Queueing…" : "Refresh Live (TWS)"}
        </button>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Account
          <select
            value={accountId}
            onChange={(e) => setAccountId(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            <option value="all">All accounts</option>
            {accounts.map((account) => (
              <option key={account.id} value={String(account.id)}>
                {account.alias ?? account.masked_account}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Instrument
          <input
            value={instrumentInput}
            onChange={(e) => setInstrumentInput(e.target.value)}
            placeholder="CL.*"
            className="w-40 rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs text-gray-600">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {loading && (
          <span className="pb-1 text-xs text-gray-400">Loading…</span>
        )}
      </div>

      {syncMessage && <p className="text-xs text-emerald-700">{syncMessage}</p>}
      {error && (
        <p className="rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">
          <thead className="border-b border-gray-200 bg-gray-50">
            <tr>
              {header("strategy", "Strategy", "left")}
              {header("group", "Group", "left")}
              <th
                scope="col"
                className="px-3 py-2 text-left font-semibold text-gray-600"
              >
                Account
              </th>
              <th
                scope="col"
                className="px-3 py-2 text-left font-semibold text-gray-600"
              >
                Instruments
              </th>
              {header("realized", "Realized")}
              {header("unrealized", "Unrealized")}
              {header("total", "Total")}
              <th
                scope="col"
                className="px-3 py-2 text-left font-semibold text-gray-600"
              >
                Status
              </th>
              <th
                scope="col"
                className="px-3 py-2 text-left font-semibold text-gray-600"
              >
                Marks
              </th>
            </tr>
          </thead>
          <tbody>
            {!loading && sorted.length === 0 && (
              <tr>
                <td
                  colSpan={9}
                  className="px-3 py-6 text-center text-sm text-gray-500"
                >
                  {filtersActive
                    ? "No trade groups match these filters."
                    : "No trade groups yet."}
                </td>
              </tr>
            )}
            {sorted.map((group) => {
              const pnl = resolvePnl(group);
              const freshness = formatFreshness(
                group.marks_as_of,
                group.live_is_stale,
              );
              const account = accounts.find((a) => a.id === group.account_id);
              return (
                <tr
                  key={group.id}
                  // The workspace reads `trade_group_id` from the query string and opens
                  // that group's detail panel.
                  onClick={() =>
                    navigate(`/strategies?trade_group_id=${group.id}`)
                  }
                  className="cursor-pointer border-b border-gray-100 hover:bg-gray-50"
                >
                  <td className="px-3 py-2 text-gray-700">
                    {strategyLabel(group)}
                  </td>
                  <td className="px-3 py-2 font-medium text-gray-900">
                    {group.name}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {account?.alias ?? account?.masked_account ?? EMPTY_CELL}
                  </td>
                  <td className="px-3 py-2 text-gray-600">
                    {formatInstruments(group.instruments)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${pnlClass(pnl.realized)}`}
                  >
                    {money(pnl.realized)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right tabular-nums ${pnlClass(pnl.unrealized)}`}
                  >
                    {money(pnl.unrealized)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-semibold tabular-nums ${pnlClass(pnl.total)}`}
                  >
                    {money(pnl.total)}
                  </td>
                  <td className="px-3 py-2 text-gray-600">{group.status}</td>
                  <td
                    className={`px-3 py-2 text-xs ${FRESHNESS_CLASS[freshness.tone]}`}
                    title={freshness.title}
                  >
                    {freshness.label}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
