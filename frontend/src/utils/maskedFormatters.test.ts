import { describe, expect, test } from "bun:test";
import { makeFormatters } from "./maskedFormatters";
import { PRIVACY_MASK } from "./privacy";

describe("makeFormatters with privacy off", () => {
  const f = makeFormatters(false);

  test("money formats and keeps the caller's fallback", () => {
    expect(f.money(1234.5)).toBe("1,234.50");
    expect(f.money(null)).toBe("—");
    expect(f.money(null, "-")).toBe("-");
  });

  test("quantity and masked pass the value through untouched", () => {
    expect(f.quantity(3)).toBe(3);
    expect(f.masked("—")).toBe("—");
    expect(f.masked(null)).toBeNull();
  });

  test("percent formats a fraction", () => {
    expect(f.percent(0.2453)).toBe("24.5%");
    expect(f.percent(undefined, "n/a")).toBe("n/a");
  });

  test("pnl is plain money", () => {
    expect(f.pnl(1250, 10000)).toBe("1,250.00");
    expect(f.pnl(null, 10000)).toBe("—");
  });
});

describe("makeFormatters with privacy on", () => {
  const f = makeFormatters(true);

  test("money, quantity, percent and masked all return the mask", () => {
    expect(f.money(1234.5)).toBe(PRIVACY_MASK);
    expect(f.money(null, "-")).toBe(PRIVACY_MASK);
    expect(f.quantity(3)).toBe(PRIVACY_MASK);
    expect(f.percent(0.2453)).toBe(PRIVACY_MASK);
    expect(f.masked("abc")).toBe(PRIVACY_MASK);
    expect(f.masked(null)).toBe(PRIVACY_MASK);
  });

  test("pnl shows a relative return, falling back to the mask", () => {
    expect(f.pnl(1250, 10000)).toBe("+12.5%");
    expect(f.pnl(-300, 6000)).toBe("-5.0%");
    expect(f.pnl(null, 6000)).toBe(PRIVACY_MASK);
    expect(f.pnl(100, 0)).toBe(PRIVACY_MASK);
  });
});
