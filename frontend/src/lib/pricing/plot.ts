// Expected-P&L response → chart traces: one line per sampled day, spot on the
// x axis. Plain objects, so this stays testable and the plotly dependency is
// confined to the chart component.

import type { ExpectedPnlResponse } from "../../types/pricing";

export interface PnlTrace {
  x: number[];
  y: number[];
  type: "scatter";
  mode: "lines";
  name: string;
}

// At most about ten day-lines, always including the last day, each sorted by
// spot. Null when there is nothing to plot.
export function buildPlotTraces(
  data: ExpectedPnlResponse | null,
): { data: PnlTrace[] } | null {
  if (!data?.model_outputs?.pnl_records?.length) return null;
  const records = data.model_outputs.pnl_records;
  const byDay = new Map<number, { spots: number[]; values: number[] }>();
  for (const r of records) {
    let entry = byDay.get(r.days_into_future);
    if (!entry) {
      entry = { spots: [], values: [] };
      byDay.set(r.days_into_future, entry);
    }
    entry.spots.push(r.spot_price);
    entry.values.push(r.value);
  }
  const days = [...byDay.keys()].sort((a, b) => a - b);
  const step = Math.max(1, Math.floor(days.length / 10));
  const sampled = days.filter(
    (_, i) => i % step === 0 || i === days.length - 1,
  );
  const traces = sampled.map((day) => {
    const entry = byDay.get(day)!;
    const paired = entry.spots.map((s, i) => ({ s, v: entry.values[i] }));
    paired.sort((a, b) => a.s - b.s);
    return {
      x: paired.map((p) => p.s),
      y: paired.map((p) => p.v),
      type: "scatter" as const,
      mode: "lines" as const,
      name: `Day ${day}`,
    };
  });
  return { data: traces };
}
