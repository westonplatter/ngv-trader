import { describe, expect, test } from "bun:test";
import {
  formatDate,
  formatDateTime,
  formatDuration,
  formatExpiry,
  parseTime,
} from "./date";

describe("formatExpiry", () => {
  test("rewrites IBKR YYYYMMDD as YYYY-MM-DD", () => {
    expect(formatExpiry("20260321")).toBe("2026-03-21");
  });

  test("passes already-dashed or odd-length values through", () => {
    expect(formatExpiry("2026-03-21")).toBe("2026-03-21");
    expect(formatExpiry("202603")).toBe("202603");
  });

  test("falls back for missing values", () => {
    expect(formatExpiry(null)).toBe("—");
    expect(formatExpiry(undefined)).toBe("—");
    expect(formatExpiry("")).toBe("—");
    expect(formatExpiry(null, "-")).toBe("-");
  });
});

describe("parseTime", () => {
  test("parses ISO timestamps to epoch ms", () => {
    expect(parseTime("2026-03-21T14:30:00Z")).toBe(
      Date.UTC(2026, 2, 21, 14, 30, 0),
    );
  });

  test("returns null for missing or unparseable input", () => {
    expect(parseTime(null)).toBeNull();
    expect(parseTime(undefined)).toBeNull();
    expect(parseTime("")).toBeNull();
    expect(parseTime("not a date")).toBeNull();
  });
});

describe("formatDate / formatDateTime", () => {
  // Locale output varies by runner, so assert the fallback path and that a
  // valid timestamp yields something other than the fallback.
  test("fall back for missing or unparseable input", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate("garbage")).toBe("—");
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("garbage", "never")).toBe("never");
  });

  test("render a valid timestamp", () => {
    const iso = "2026-03-21T14:30:00Z";
    expect(formatDate(iso)).not.toBe("—");
    expect(formatDateTime(iso)).not.toBe("—");
    expect(formatDateTime(iso).length).toBeGreaterThan(formatDate(iso).length);
  });
});

describe("formatDuration", () => {
  test("seconds under a minute", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(1500)).toBe("1s");
    expect(formatDuration(59_999)).toBe("59s");
  });

  test("minutes and seconds under an hour", () => {
    expect(formatDuration(60_000)).toBe("1m 0s");
    expect(formatDuration(95_000)).toBe("1m 35s");
  });

  test("hours and minutes", () => {
    expect(formatDuration(3_600_000)).toBe("1h 0m");
    expect(formatDuration(7_260_000)).toBe("2h 1m");
  });

  test("clamps negatives and falls back for null", () => {
    expect(formatDuration(-5000)).toBe("0s");
    expect(formatDuration(null)).toBe("—");
  });
});
