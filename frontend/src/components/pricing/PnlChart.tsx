// The expected-P&L chart. The only file that imports plotly, so the route can
// be lazy-loaded around it.

import Plot from "react-plotly.js";
import type { PnlTrace } from "../../lib/pricing/plot";

export default function PnlChart({ traces }: { traces: PnlTrace[] }) {
  return (
    <Plot
      data={traces}
      layout={{
        title: { text: "Expected PnL Over Time" },
        xaxis: { title: { text: "Spot Price" } },
        yaxis: { title: { text: "PnL" } },
        height: 500,
        margin: { t: 40, r: 120, b: 50, l: 60 },
        showlegend: true,
        legend: { orientation: "v", x: 1.02, y: 1 },
      }}
      config={{ responsive: true }}
      style={{ width: "100%" }}
    />
  );
}
