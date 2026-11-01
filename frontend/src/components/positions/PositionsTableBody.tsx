// The positions table: sortable header, the per-column filter row, and one
// PositionCell per visible column of each row.

import {
  isSortableColumn,
  type PositionFilters,
  type SortColumn,
  type SortState,
} from "../../lib/positions/view";
import { ariaSort, sortIndicator } from "../../lib/tableSort";
import type { Position } from "../../types/positions";
import {
  FILTER_TINT,
  HEADER_TINT,
  columnGroup,
  type PositionColumn,
} from "./columns";
import PositionCell from "./PositionCell";

function TextFilter({
  value,
  onChange,
  clearLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  clearLabel: string;
}) {
  return (
    <div className="flex items-center gap-1">
      <input
        type="text"
        placeholder="Regex filter"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-28 rounded border border-gray-300 px-2 py-0.5 text-xs text-gray-700"
      />
      {value ? (
        <button
          type="button"
          onClick={() => onChange("")}
          className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
          title={clearLabel}
          aria-label={clearLabel}
        >
          ×
        </button>
      ) : null}
    </div>
  );
}

function ColumnFilter({
  column,
  filters,
  onFilter,
}: {
  column: PositionColumn;
  filters: PositionFilters;
  onFilter: <K extends keyof PositionFilters>(
    key: K,
    value: PositionFilters[K],
  ) => void;
}) {
  switch (column.key) {
    case "symbol":
      return (
        <TextFilter
          value={filters.symbol}
          onChange={(v) => onFilter("symbol", v)}
          clearLabel="Clear symbol filter"
        />
      );
    case "local_symbol":
      return (
        <TextFilter
          value={filters.localSymbol}
          onChange={(v) => onFilter("localSymbol", v)}
          clearLabel="Clear local symbol filter"
        />
      );
    case "sec_type":
      return (
        <TextFilter
          value={filters.secType}
          onChange={(v) => onFilter("secType", v)}
          clearLabel="Clear sec type filter"
        />
      );
    case "dte":
      return (
        <div className="flex items-center gap-1">
          <input
            type="number"
            placeholder="min"
            value={filters.dteMin}
            onChange={(e) => onFilter("dteMin", e.target.value)}
            className="w-14 rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-700"
          />
          <input
            type="number"
            placeholder="max"
            value={filters.dteMax}
            onChange={(e) => onFilter("dteMax", e.target.value)}
            className="w-14 rounded border border-gray-300 px-1.5 py-0.5 text-xs text-gray-700"
          />
          {filters.dteMin || filters.dteMax ? (
            <button
              type="button"
              onClick={() => {
                onFilter("dteMin", "");
                onFilter("dteMax", "");
              }}
              className="rounded border border-gray-300 px-1 text-xs text-gray-600 hover:bg-gray-100"
              title="Clear DTE filters"
              aria-label="Clear DTE filters"
            >
              ×
            </button>
          ) : null}
        </div>
      );
    default:
      return null;
  }
}

export default function PositionsTableBody({
  columns,
  rows,
  filters,
  onFilter,
  sort,
  onToggleSort,
  privacyMode,
  onAssign,
  onUnassign,
  onChanged,
}: {
  columns: PositionColumn[];
  rows: Position[];
  filters: PositionFilters;
  onFilter: <K extends keyof PositionFilters>(
    key: K,
    value: PositionFilters[K],
  ) => void;
  sort: SortState;
  onToggleSort: (column: SortColumn) => void;
  privacyMode: boolean;
  onAssign: (pos: Position, groupId: number) => void;
  onUnassign: (pos: Position, groupId: number) => void;
  onChanged: () => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-sm">
        <thead>
          <tr className="bg-gray-100 text-left">
            {columns.map((col) => {
              const sortKey = isSortableColumn(col.key) ? col.key : null;
              return (
                <th
                  key={col.key}
                  aria-sort={sortKey ? ariaSort(sort, sortKey) : undefined}
                  className={`px-3 py-2 font-semibold text-gray-700 whitespace-nowrap ${HEADER_TINT[columnGroup(col.key)]}`}
                >
                  {sortKey ? (
                    <button
                      type="button"
                      onClick={() => onToggleSort(sortKey)}
                      className="inline-flex items-center gap-1 text-gray-700 hover:text-gray-900"
                      title={`Cycle ${col.label} sort`}
                    >
                      <span>{col.label}</span>
                      <span
                        aria-hidden="true"
                        className={
                          ariaSort(sort, sortKey) !== "none"
                            ? "text-gray-900"
                            : "text-gray-400"
                        }
                      >
                        {sortIndicator(sort, sortKey)}
                      </span>
                    </button>
                  ) : (
                    col.label
                  )}
                </th>
              );
            })}
          </tr>
          <tr className="bg-gray-50 text-left">
            {columns.map((col) => (
              <th
                key={`filter-${col.key}`}
                className={`px-3 py-1 font-normal text-gray-700 whitespace-nowrap ${FILTER_TINT[columnGroup(col.key)]}`}
              >
                <ColumnFilter column={col} filters={filters} onFilter={onFilter} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-6 text-center text-gray-500"
              >
                No positions match the current filters.
              </td>
            </tr>
          )}
          {rows.map((pos) => (
            <tr
              key={pos.id}
              className="group border-b border-gray-200 hover:bg-gray-50"
            >
              {columns.map((col) => (
                <PositionCell
                  key={col.key}
                  pos={pos}
                  column={col}
                  privacyMode={privacyMode}
                  onAssign={onAssign}
                  onUnassign={onUnassign}
                  onChanged={onChanged}
                />
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
