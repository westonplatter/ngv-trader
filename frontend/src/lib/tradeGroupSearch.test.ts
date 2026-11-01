import { describe, expect, test } from "bun:test";
import {
  contractSymbol,
  escapeRegex,
  mergeRecommended,
  popoverPosition,
  recommendedSearchParams,
  stepHighlight,
  textSearchParams,
} from "./tradeGroupSearch";
import type { TradeGroupResult } from "../types/tradeGroups";

function group(id: number): TradeGroupResult {
  return { id } as TradeGroupResult;
}

describe("contractSymbol", () => {
  test("takes the first token, upper-cased", () => {
    expect(contractSymbol("GLD")).toBe("GLD");
    expect(contractSymbol("gld Dec31'25 412 CALL")).toBe("GLD");
    expect(contractSymbol("  CL   Sep'26 Future ")).toBe("CL");
  });

  test("is null for a missing or blank name", () => {
    expect(contractSymbol(null)).toBeNull();
    expect(contractSymbol("   ")).toBeNull();
  });
});

describe("escapeRegex", () => {
  test("escapes regex metacharacters", () => {
    expect(escapeRegex("BRK.B")).toBe("BRK\\.B");
    expect(escapeRegex("A+B(C)")).toBe("A\\+B\\(C\\)");
    expect(escapeRegex("CL")).toBe("CL");
  });
});

describe("search params", () => {
  test("text search sets q only when there is text, and always limits to open", () => {
    expect(textSearchParams("  oil ").toString()).toBe(
      "q=oil&limit=20&status=open",
    );
    expect(textSearchParams("   ").toString()).toBe("limit=20&status=open");
  });

  test("recommended search anchors an escaped symbol at the start", () => {
    const params = recommendedSearchParams("BRK.B");
    expect(params.get("instrument")).toBe("^BRK\\.B");
    expect(params.get("limit")).toBe("20");
    expect(params.get("status")).toBe("open");
  });
});

describe("mergeRecommended", () => {
  test("floats the top two recommendations and removes them from the rest", () => {
    const merged = mergeRecommended(
      [group(5), group(3), group(9)],
      [group(1), group(3), group(5), group(9)],
    );
    expect(merged.map((g) => g.id)).toEqual([5, 3, 1, 9]);
  });

  test("with no recommendations returns the full list", () => {
    expect(mergeRecommended([], [group(1), group(2)]).map((g) => g.id)).toEqual(
      [1, 2],
    );
  });
});

describe("stepHighlight", () => {
  test("wraps at both ends", () => {
    expect(stepHighlight(0, 1, 3)).toBe(1);
    expect(stepHighlight(2, 1, 3)).toBe(0);
    expect(stepHighlight(0, -1, 3)).toBe(2);
  });

  test("an empty list stays at zero", () => {
    expect(stepHighlight(0, 1, 0)).toBe(0);
  });
});

describe("popoverPosition", () => {
  const rect = { top: 100, bottom: 120, left: 40, width: 150 };

  test("opens below the input with room to spare, at least 240px wide", () => {
    expect(popoverPosition(rect, 900)).toEqual({
      top: 124,
      left: 40,
      width: 240,
      flipUp: false,
    });
  });

  test("flips above when under 260px of room remains", () => {
    expect(popoverPosition({ ...rect, bottom: 700 }, 900)).toMatchObject({
      top: 100,
      flipUp: true,
    });
  });

  test("keeps a wider trigger's width", () => {
    expect(popoverPosition({ ...rect, width: 400 }, 900).width).toBe(400);
  });
});
