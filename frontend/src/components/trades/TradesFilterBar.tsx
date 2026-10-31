// The account chips, the Range / Group / Columns segmented controls, and the
// con_id deep-link notice.

import {
  TIME_RANGES,
  type AccountOption,
  type GroupStatus,
} from "../../lib/trades/view";
import type { TradeFilterState } from "./useTradeFilters";

function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  titleFor,
}: {
  label: string;
  options: readonly { id: T; label: string }[];
  value: T;
  onChange: (id: T) => void;
  titleFor?: (id: T) => string;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </span>
      <div className="inline-flex items-center gap-0.5 rounded-md bg-gray-100 p-0.5">
        {options.map((opt) => (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            title={titleFor?.(opt.id)}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              value === opt.id
                ? "bg-white text-gray-900 shadow-sm"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

const GROUP_OPTIONS: readonly { id: GroupStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "grouped", label: "Grouped" },
  { id: "ungrouped", label: "Ungrouped" },
];

const COLUMN_OPTIONS: readonly { id: "simple" | "all"; label: string }[] = [
  { id: "simple", label: "Simple" },
  { id: "all", label: "All" },
];

export default function TradesFilterBar({
  accounts,
  state,
  onTimeRange,
}: {
  accounts: AccountOption[];
  state: TradeFilterState;
  // The page wraps setTimeRange so the relative-range clock is re-read first.
  onTimeRange: (id: string) => void;
}) {
  const { filters, showDetails, conId } = state;
  return (
    <>
      {accounts.length > 1 && (
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => state.setAccount("all")}
            className={`rounded px-2.5 py-1 text-xs font-medium uppercase tracking-wide ${
              filters.account === "all"
                ? "bg-gray-900 text-white"
                : "bg-gray-100 text-gray-700 hover:bg-gray-200"
            }`}
          >
            All
          </button>
          {accounts.map((acct) => (
            <button
              key={acct.id}
              type="button"
              onClick={() => state.setAccount(acct.id)}
              className={`rounded px-2.5 py-1 text-xs font-medium tracking-wide ${
                filters.account === acct.id
                  ? "bg-gray-900 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              }`}
            >
              {acct.label}
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <Segmented
          label="Range"
          options={TIME_RANGES}
          value={filters.timeRange}
          onChange={onTimeRange}
        />
        <Segmented
          label="Group"
          options={GROUP_OPTIONS}
          value={filters.groupStatus}
          onChange={state.setGroupStatus}
        />
        <Segmented
          label="Columns"
          options={COLUMN_OPTIONS}
          value={showDetails ? "all" : "simple"}
          onChange={(id) => state.setShowDetails(id === "all")}
          titleFor={(id) =>
            id === "all"
              ? "Show the Parent Exec ID, Order Ref, Exec ID, and Con ID columns"
              : "Hide the id/reference columns"
          }
        />
      </div>

      {conId !== null && (
        <p className="text-sm text-gray-600">
          Showing all executions for Contract ID{" "}
          <span className="font-mono font-medium">{conId}</span> across all
          time and accounts.{" "}
          <button
            type="button"
            onClick={state.clearConId}
            className="text-blue-600 hover:underline"
          >
            Clear
          </button>
        </p>
      )}
    </>
  );
}
