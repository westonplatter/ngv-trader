// Freshness-badge timestamp formatting.
//
// The branch under test is the whole point of the helper: a bare "11:09 PM" on
// a days-old overlay capture read as tonight, which made the stale badge least
// legible exactly when staleness mattered.
import { afterEach, describe, expect, setSystemTime, test } from "bun:test";

import { formatMarkTime } from "./markTime";

const NOW = new Date("2026-08-29T14:00:00");

afterEach(() => {
  setSystemTime();
});

function at(iso: string): string {
  setSystemTime(NOW);
  return formatMarkTime(iso);
}

describe("formatMarkTime", () => {
  test("shows time only for a timestamp from today", () => {
    const out = at("2026-08-29T09:30:00");
    expect(out).toMatch(/^\d{1,2}:\d{2}/);
    expect(out).not.toContain("Aug");
  });

  test("qualifies an older timestamp with its date", () => {
    // The four-day-old overlay capture behind the misleading badge.
    const out = at("2026-08-25T23:09:14");
    expect(out).toContain("Aug");
    expect(out).toContain("25");
    expect(out).toMatch(/\d{1,2}:\d{2}/);
  });

  test("qualifies yesterday too, not just multi-day gaps", () => {
    expect(at("2026-08-28T23:09:14")).toContain("Aug");
  });

  test("returns an empty string for missing or unparseable input", () => {
    expect(formatMarkTime(null)).toBe("");
    expect(formatMarkTime(undefined)).toBe("");
    expect(formatMarkTime("")).toBe("");
    expect(formatMarkTime("not a date")).toBe("");
  });
});

describe("single source of truth", () => {
  // This helper existed in three private copies (PositionsTable,
  // TradeTaggingPage, strategyPnl). Two were merged and the third was missed,
  // so the Strategy P&L table kept printing a bare time on a days-old capture.
  // Grepping for the next copy is not a plan; this is.
  const FRESHNESS_CONSUMERS = [
    "src/components/PositionsTable.tsx",
    "src/components/TradeTaggingPage.tsx",
    "src/lib/strategyPnl.ts",
  ];

  test.each(FRESHNESS_CONSUMERS)(
    "%s formats mark freshness via the shared helper, not its own",
    async (path) => {
      const text = await Bun.file(path).text();
      expect(text).toContain("formatMarkTime");
      // A local toLocaleTimeString here means a private copy has grown back.
      expect(text).not.toContain("toLocaleTimeString");
    },
  );
});
