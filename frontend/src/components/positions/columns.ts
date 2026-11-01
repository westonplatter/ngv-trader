// Column catalog for the Positions table: order, labels, which columns the
// greeks toggle hides, and the live/settled banding each column belongs to.

import type { Position } from "../../types/positions";

export interface PositionColumn {
  key: keyof Position;
  label: string;
}

export const COLUMNS: readonly PositionColumn[] = [
  { key: "con_id", label: "Con ID" },
  { key: "account_alias", label: "Account" },
  { key: "trade_groups", label: "Trade Group" },
  { key: "tags", label: "Tags" },
  { key: "open_task_count", label: "Tasks" },
  { key: "symbol", label: "Symbol" },
  { key: "sec_type", label: "Sec Type" },
  { key: "contract_display_name", label: "Contract" },
  { key: "local_symbol", label: "Local Symbol" },
  { key: "last_trade_date", label: "Last Trade Date" },
  { key: "option_expiry_date", label: "Expiry" },
  { key: "dte", label: "DTE" },
  { key: "strike", label: "Strike" },
  { key: "right", label: "Call/Put" },
  { key: "multiplier", label: "Multiplier" },
  { key: "position", label: "Position" },
  { key: "avg_cost", label: "Avg Cost" },
  { key: "mark_price", label: "Mark" },
  { key: "position_value", label: "Value" },
  { key: "fifo_pnl_unrealized", label: "Unrealized PnL" },
  { key: "mark", label: "Live Mark" },
  { key: "live_unrealized", label: "Live Unrealized" },
  { key: "iv", label: "IV" },
  { key: "delta", label: "Delta" },
  { key: "gamma", label: "Gamma" },
  { key: "theta", label: "Theta" },
  { key: "vega", label: "Vega" },
  { key: "extrinsic_value", label: "Extrinsic" },
  { key: "intrinsic_value", label: "Intrinsic" },
  { key: "source", label: "Freshness" },
];

// Secondary greeks hidden unless "Show greeks" is toggled on (keeps the default
// view compact; IV / Delta / Extrinsic / Intrinsic stay visible).
const GREEK_KEYS: readonly (keyof Position)[] = ["gamma", "theta", "vega"];

export function visibleColumns(showGreeks: boolean): PositionColumn[] {
  return COLUMNS.filter((c) => showGreeks || !GREEK_KEYS.includes(c.key));
}

// Column provenance, so the table can visually band live (TWS overlay) columns
// apart from settled (FlexQuery snapshot) columns. Identity/contract columns are
// neutral and left untinted.
export type ColumnGroup = "live" | "flex" | "neutral";

const LIVE_KEYS = new Set<keyof Position>([
  "mark",
  "live_unrealized",
  "iv",
  "delta",
  "gamma",
  "theta",
  "vega",
  "extrinsic_value",
  "intrinsic_value",
  "source",
]);

// Live overlay *value* columns (excludes the "source"/Freshness badge column,
// which renders its own stale state). Blanked when the row's live overlay is
// stale so old TWS marks/greeks aren't shown as if current.
export const LIVE_OVERLAY_VALUE_KEYS = new Set<keyof Position>([
  "mark",
  "live_unrealized",
  "iv",
  "delta",
  "gamma",
  "theta",
  "vega",
  "extrinsic_value",
  "intrinsic_value",
]);

const FLEX_KEYS = new Set<keyof Position>([
  "mark_price",
  "position_value",
  "fifo_pnl_unrealized",
]);

export function columnGroup(key: keyof Position): ColumnGroup {
  if (LIVE_KEYS.has(key)) return "live";
  if (FLEX_KEYS.has(key)) return "flex";
  return "neutral";
}

// Tints per band. Body cells use group-hover so the row highlight still reads
// through the column tint. Neutral columns fall back to the row/thead defaults.
export const HEADER_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-100",
  flex: "bg-amber-100",
  neutral: "",
};
export const FILTER_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-50",
  flex: "bg-amber-50",
  neutral: "",
};
export const CELL_TINT: Record<ColumnGroup, string> = {
  live: "bg-sky-50 group-hover:bg-sky-100",
  flex: "bg-amber-50 group-hover:bg-amber-100",
  neutral: "",
};
