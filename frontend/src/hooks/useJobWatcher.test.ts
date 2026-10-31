import { describe, expect, test } from "bun:test";
import { shouldPoll } from "./useJobWatcher";

const NOW = 1_000_000;
const watch = (lastCheckedAgoMs: number, deadlineInMs = 60_000) => ({
  lastChecked: NOW - lastCheckedAgoMs,
  deadline: NOW + deadlineInMs,
});

describe("shouldPoll", () => {
  test("polls every 2s while the stream is down", () => {
    expect(shouldPoll(watch(1_000), NOW, false)).toBe(false);
    expect(shouldPoll(watch(2_000), NOW, false)).toBe(true);
    expect(shouldPoll(watch(3_000), NOW, false)).toBe(true);
  });

  test("backs off to a slow poll while the stream is connected", () => {
    expect(shouldPoll(watch(3_000), NOW, true)).toBe(false);
    expect(shouldPoll(watch(9_999), NOW, true)).toBe(false);
    expect(shouldPoll(watch(10_000), NOW, true)).toBe(true);
    expect(shouldPoll(watch(11_000), NOW, true)).toBe(true);
  });

  test("never polls a watch past its deadline", () => {
    expect(shouldPoll(watch(60_000, -1), NOW, false)).toBe(false);
    expect(shouldPoll(watch(60_000, -1), NOW, true)).toBe(false);
  });
});
