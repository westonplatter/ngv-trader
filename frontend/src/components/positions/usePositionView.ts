// How the operator is looking at the positions: filters, sort, the greeks
// toggle, and everything derived from them (visible columns, the rows to
// render, the account chips, the totals line). The math is in lib/positions.

import { useCallback, useMemo, useState } from "react";
import {
  DEFAULT_SORT,
  EMPTY_FILTERS,
  accountAliases,
  filterPositions,
  nextSort,
  positionTotals,
  sortPositions,
  type PositionFilters,
  type PositionTotals,
  type SortColumn,
  type SortState,
} from "../../lib/positions/view";
import type { Position } from "../../types/positions";
import { visibleColumns, type PositionColumn } from "./columns";

export interface PositionView {
  filters: PositionFilters;
  setFilter: <K extends keyof PositionFilters>(
    key: K,
    value: PositionFilters[K],
  ) => void;
  // Clears the column filters; the account chips are a separate choice.
  clearFilters: () => void;
  sort: SortState;
  toggleSort: (column: SortColumn) => void;
  showGreeks: boolean;
  toggleGreeks: () => void;
  columns: PositionColumn[];
  rows: Position[];
  accountAliases: string[];
  totals: PositionTotals;
}

export function usePositionView(positions: Position[]): PositionView {
  const [filters, setFilters] = useState<PositionFilters>(EMPTY_FILTERS);
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);
  const [showGreeks, setShowGreeks] = useState(false);

  const setFilter = useCallback(
    <K extends keyof PositionFilters>(key: K, value: PositionFilters[K]) =>
      setFilters((current) => ({ ...current, [key]: value })),
    [],
  );
  const clearFilters = useCallback(
    () =>
      setFilters((current) => ({ ...EMPTY_FILTERS, account: current.account })),
    [],
  );
  const toggleSort = useCallback(
    (column: SortColumn) => setSort((current) => nextSort(current, column)),
    [],
  );
  const toggleGreeks = useCallback(() => setShowGreeks((v) => !v), []);

  const columns = useMemo(() => visibleColumns(showGreeks), [showGreeks]);
  const aliases = useMemo(() => accountAliases(positions), [positions]);
  const rows = useMemo(
    () => sortPositions(filterPositions(positions, filters), sort),
    [positions, filters, sort],
  );
  const totals = useMemo(() => positionTotals(rows), [rows]);

  return {
    filters,
    setFilter,
    clearFilters,
    sort,
    toggleSort,
    showGreeks,
    toggleGreeks,
    columns,
    rows,
    accountAliases: aliases,
    totals,
  };
}
