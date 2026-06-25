// Shared trade-group shape and label helper used by the Trades and Positions
// tables and the trade-group search picker.

export interface TradeGroupResult {
  id: number;
  account_id: number | null;
  name: string;
  status: string;
  primary_strategy_value: string | null;
}

export function tradeGroupLabel(group: TradeGroupResult): string {
  const strategy = group.primary_strategy_value ?? "No Strategy";
  return `${strategy} > ${group.name}`;
}
