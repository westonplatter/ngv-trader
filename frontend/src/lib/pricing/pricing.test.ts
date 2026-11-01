import { describe, expect, test } from "bun:test";
import type { ChainEntry, ExpectedPnlResponse } from "../../types/pricing";
import {
  applyPriceJobResult,
  createEmptyLeg,
  entriesForExpiry,
  expiryOptions,
  formatExpiration,
  hasPricingData,
  legFromChainEntry,
  legsToApi,
  legsToSaved,
  midPrice,
  parseQuantityInput,
  priceJobPayload,
  resetLegFields,
  savedLegsToRows,
  spotRange,
  uniqueStrikes,
} from "./legs";
import { buildPlotTraces } from "./plot";

function entry(overrides: Partial<ChainEntry>): ChainEntry {
  return {
    symbol: "CL",
    trading_class: "LO",
    expiration: "20270319",
    strike: 70,
    right: "C",
    dte: 120,
    underlying_con_id: 1,
    exchange: "NYMEX",
    sec_type: "FOP",
    con_id: null,
    display_name: "CL Mar'27 70 Call",
    is_monthly: true,
    bid: null,
    ask: null,
    last: null,
    iv: null,
    delta: null,
    und_price: null,
    observed_at: null,
    ...overrides,
  };
}

describe("quantity and price helpers", () => {
  test("parseQuantityInput treats blank as zero and rejects junk", () => {
    expect(parseQuantityInput("3")).toBe(3);
    expect(parseQuantityInput(" -2.5 ")).toBe(-2.5);
    expect(parseQuantityInput("")).toBe(0);
    expect(parseQuantityInput("x")).toBeNull();
  });

  test("midPrice averages when both sides exist, else whichever is present", () => {
    expect(midPrice(1, 3)).toBe(2);
    expect(midPrice(1, null)).toBe(1);
    expect(midPrice(null, 3)).toBe(3);
    expect(midPrice(null, null)).toBeNull();
  });

  test("hasPricingData needs any of bid, ask, iv", () => {
    expect(hasPricingData({ bid: null, ask: null })).toBe(false);
    expect(hasPricingData({ bid: null, ask: null, iv: 0.2 })).toBe(true);
  });

  test("spotRange seeds a ±20% window with two decimals", () => {
    expect(spotRange(100)).toEqual({ spot: "100.00", min: "80.00", max: "120.00" });
  });
});

describe("saved structures round trip", () => {
  test("legsToSaved drops the transient fields and savedLegsToRows restores defaults", () => {
    const leg = { ...createEmptyLeg(), strike: 70, quantity: 2, quantityInput: "2", volume: 10, fetchStatus: "done" as const };
    const saved = legsToSaved([leg]);
    expect(saved[0]).not.toHaveProperty("volume");
    expect(saved[0].strike).toBe(70);
    const rows = savedLegsToRows(saved);
    expect(rows[0].quantityInput).toBe("2");
    expect(rows[0].volume).toBeNull();
    expect(rows[0].fetchStatus).toBe("idle");
    expect(rows[0].id).not.toBe(leg.id);
  });

  test("legsToApi uses the pricing service's field names", () => {
    const api = legsToApi([{ ...createEmptyLeg(), optionType: "p", tradePrice: 1.5 }]);
    expect(api[0]).toMatchObject({ option_type: "p", trade_price: 1.5, rate: null, underlying: null });
  });

  test("resetLegFields keeps the quantity and clears the selection", () => {
    const patch = resetLegFields({ ...createEmptyLeg(), quantity: 4, strike: 70 }, "cash");
    expect(patch.optionType).toBe("cash");
    expect(patch.strike).toBeNull();
    expect(patch.quantityInput).toBe("4");
  });
});

describe("option cascade", () => {
  const chain = [
    entry({ expiration: "20270319", dte: 120, strike: 70 }),
    entry({ expiration: "20270319", dte: 120, strike: 75 }),
    entry({ expiration: "20270115", dte: 60, strike: 70, is_monthly: false, trading_class: "LO2" }),
    entry({ expiration: "20270115", dte: 60, strike: 65, is_monthly: false, trading_class: "LO2" }),
  ];

  test("formatExpiration distinguishes monthlies from weeklies", () => {
    expect(formatExpiration("20270319", true)).toBe("Mar 2027");
    expect(formatExpiration("20270115", false)).toBe("15-Jan-2027");
    expect(formatExpiration("bad", true)).toBe("bad");
  });

  test("expiryOptions dedupes by class+expiry, labels weeklies, sorts by dte", () => {
    const options = expiryOptions(chain);
    expect(options.map((o) => o.key)).toEqual(["LO2-20270115", "LO-20270319"]);
    expect(options[0].label).toBe("15-Jan-2027 [LO2] (60d)");
    expect(options[1].label).toBe("Mar 2027 (120d)");
  });

  test("entriesForExpiry and uniqueStrikes narrow to one expiry, strikes ascending", () => {
    const entries = entriesForExpiry(chain, "20270115", "LO2");
    expect(uniqueStrikes(entries)).toEqual([65, 70]);
    expect(entriesForExpiry(chain, null, "LO2")).toEqual([]);
  });

  test("legFromChainEntry marks a quoted entry done and an unquoted one idle", () => {
    expect(legFromChainEntry(entry({ bid: 1, ask: 2 }))).toMatchObject({
      tradePrice: 1.5,
      fetchStatus: "done",
    });
    expect(legFromChainEntry(entry({})).fetchStatus).toBe("idle");
  });

  test("priceJobPayload snapshots a known con_id and qualifies otherwise", () => {
    expect(priceJobPayload(entry({ con_id: 42 }))).toMatchObject({
      job_type: "market_data.snapshot",
      payload: { con_ids: [42] },
    });
    expect(priceJobPayload(entry({}))).toMatchObject({
      job_type: "contracts.qualify_and_snapshot",
      payload: { symbol: "CL", strike: 70, right: "C" },
    });
  });
});

describe("applyPriceJobResult", () => {
  const legs = [createEmptyLeg(), createEmptyLeg()];
  const now = () => "2026-06-21T14:30:00.000Z";

  test("a completed job fills the quote and mid on the right leg only", () => {
    const next = applyPriceJobResult(
      legs,
      legs[1].id,
      {
        id: 1,
        status: "completed",
        result: { results: [{ con_id: "7", bid: 1, ask: 3, iv: 0.25, und_price: 70 }] },
      },
      now,
    );
    expect(next[0]).toBe(legs[0]);
    expect(next[1]).toMatchObject({
      fetchStatus: "done",
      selectedConId: 7,
      bid: 1,
      ask: 3,
      tradePrice: 2,
      ivstart: 0.25,
      undPrice: 70,
      observedAt: "2026-06-21T14:30:00.000Z",
    });
  });

  test("reads results nested under snapshot and keeps old values for missing fields", () => {
    const seeded = [{ ...legs[0], bid: 9, ivstart: 0.5 }];
    const next = applyPriceJobResult(
      seeded,
      seeded[0].id,
      { id: 1, status: "completed", result: { snapshot: { results: [{ ask: 11 }] } } },
      now,
    );
    expect(next[0]).toMatchObject({ bid: 9, ask: 11, ivstart: 0.5, tradePrice: null });
  });

  test("a failed job marks the leg and an unknown leg id is a no-op", () => {
    expect(applyPriceJobResult(legs, legs[0].id, { id: 1, status: "failed" })[0].fetchStatus).toBe("error");
    expect(applyPriceJobResult(legs, "nope", { id: 1, status: "completed" })).toBe(legs);
  });
});

describe("buildPlotTraces", () => {
  test("null for an empty response", () => {
    expect(buildPlotTraces(null)).toBeNull();
    expect(
      buildPlotTraces({ model_inputs: {}, model_outputs: { min_dte: 0, pnl_records: [], pnl_records_count: 0 } }),
    ).toBeNull();
  });

  test("one trace per day, sorted by spot, sampled to about ten days plus the last", () => {
    const records = [];
    for (let day = 0; day < 25; day++) {
      for (const spot of [110, 90, 100]) {
        records.push({ spot_price: spot, days_into_future: day, value: spot - 100 + day });
      }
    }
    const data: ExpectedPnlResponse = {
      model_inputs: {},
      model_outputs: { min_dte: 0, pnl_records: records, pnl_records_count: records.length },
    };
    const traces = buildPlotTraces(data)!.data;
    expect(traces.map((t) => t.name)).toEqual([
      "Day 0", "Day 2", "Day 4", "Day 6", "Day 8", "Day 10", "Day 12",
      "Day 14", "Day 16", "Day 18", "Day 20", "Day 22", "Day 24",
    ]);
    expect(traces[0].x).toEqual([90, 100, 110]);
    expect(traces[0].y).toEqual([-10, 0, 10]);
    expect(traces[0]).toMatchObject({ type: "scatter", mode: "lines" });
  });
});
