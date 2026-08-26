// Nav configuration invariants (U5).
//
// `NavLink` matches descendant paths by default, so a nav entry whose path is a
// prefix of another entry's renders active on both pages. Adding
// `/strategies/table` next to `/strategies` is exactly that case: without
// `end: true` on Strategies, both tabs bold at once and the operator cannot tell
// which page they are on.
//
// This is config-shaped rather than render-shaped on purpose — the repo has no
// component-test harness, and the invariant is a property of NAV_ITEMS.
import { describe, expect, test } from "bun:test";

import { NAV_ITEMS } from "./navItems";

describe("NAV_ITEMS", () => {
  test("every entry whose path is a prefix of another sets end", () => {
    for (const item of NAV_ITEMS) {
      const hasNestedSibling = NAV_ITEMS.some(
        (other) => other !== item && other.path.startsWith(`${item.path}/`),
      );
      if (hasNestedSibling) {
        expect(
          item.end,
          `${item.path} has a nested sibling and must set end`,
        ).toBe(true);
      }
    }
  });

  test("exactly one entry is active on /strategies/table", () => {
    // Mirrors NavLink's matching rule: `end` compares the whole path, otherwise
    // a descendant of the entry's path counts as a match.
    const pathname = "/strategies/table";
    const active = NAV_ITEMS.filter((item) =>
      item.end
        ? pathname === item.path
        : pathname === item.path || pathname.startsWith(`${item.path}/`),
    );

    expect(active.map((item) => item.label)).toEqual(["Strategy P&L"]);
  });

  test("exactly one entry is active on /strategies", () => {
    const pathname = "/strategies";
    const active = NAV_ITEMS.filter((item) =>
      item.end
        ? pathname === item.path
        : pathname === item.path || pathname.startsWith(`${item.path}/`),
    );

    expect(active.map((item) => item.label)).toEqual(["Strategies"]);
  });

  test("nav paths are unique", () => {
    const paths = NAV_ITEMS.map((item) => item.path);
    expect(new Set(paths).size).toBe(paths.length);
  });
});
