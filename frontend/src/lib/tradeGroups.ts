// Trade-group label helper shared by the Trades and Positions tables and the
// trade-group search picker. Shapes are in ../types/tradeGroups.

import type { TradeGroupResult } from "../types/tradeGroups";

export function tradeGroupLabel(group: TradeGroupResult): string {
  const strategy = group.primary_strategy_value ?? "No Strategy";
  return `${strategy} > ${group.name}`;
}
