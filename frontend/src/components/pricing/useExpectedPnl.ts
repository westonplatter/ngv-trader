// The Calculate PnL call to the pricing service (a different backend, hence
// the base override). Validation failures and request failures reject with
// a message the page shows; a new run clears the previous result first.

import { useCallback, useState } from "react";
import { api } from "../../lib/api";
import { legsToApi, type LegRow } from "../../lib/pricing/legs";
import type { ExpectedPnlResponse } from "../../types/pricing";

const PRICING_API_BASE = "/pricing-api";

export interface PnlInputs {
  spotPrice: string;
  spotMin: string;
  spotMax: string;
  dayStep: string;
  strikeStep: string;
  legs: LegRow[];
}

export interface ExpectedPnl {
  loading: boolean;
  data: ExpectedPnlResponse | null;
  calculate: (inputs: PnlInputs) => Promise<void>;
}

export function useExpectedPnl(): ExpectedPnl {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<ExpectedPnlResponse | null>(null);

  const calculate = useCallback(async (inputs: PnlInputs) => {
    const spot = parseFloat(inputs.spotPrice);
    const sMin = parseFloat(inputs.spotMin);
    const sMax = parseFloat(inputs.spotMax);
    if (isNaN(spot) || isNaN(sMin) || isNaN(sMax)) {
      throw new Error("Spot price, min, and max are required.");
    }
    if (inputs.legs.length === 0) {
      throw new Error("Add at least one leg.");
    }
    setLoading(true);
    setData(null);
    const daysIntoFuture = Math.max(...inputs.legs.map((l) => l.dte), 1);
    try {
      const result = await api.post<ExpectedPnlResponse>(
        "/expected-pnl",
        {
          spot_price: spot,
          legs: legsToApi(inputs.legs),
          spot_min: sMin,
          spot_max: sMax,
          days_into_future: daysIntoFuture,
          day_step: parseInt(inputs.dayStep) || 1,
          strike_step: parseFloat(inputs.strikeStep) || 1,
        },
        { base: PRICING_API_BASE },
      );
      setData(result);
    } finally {
      setLoading(false);
    }
  }, []);

  return { loading, data, calculate };
}
