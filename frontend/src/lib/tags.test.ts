import { describe, expect, test } from "bun:test";
import { itemKey, itemRoute, nextTaskStatus, normalizeTagValue } from "./tags";

describe("tag helpers", () => {
  test("normalization folds case, spaces, dashes, and underscores", () => {
    for (const spelling of [
      "Long Beta",
      "long_beta",
      " long--beta ",
      "LONG-BETA",
    ])
      expect(normalizeTagValue(spelling)).toBe("long-beta");
  });

  test("itemKey uses the API's typed key", () => {
    expect(itemKey({ entity_type: "trade", id: 8 })).toBe("trade:8");
    expect(
      itemKey({ entity_type: "position", account_id: 1, con_id: 400000002 }),
    ).toBe("position:1:400000002");
    expect(
      itemKey({ entity_type: "live_execution", ib_exec_id: "0000demo.1" }),
    ).toBe("live_execution:0000demo.1");
  });

  test("status cycles todo → in progress → done → todo", () => {
    expect(nextTaskStatus("todo")).toBe("in_progress");
    expect(nextTaskStatus("in_progress")).toBe("done");
    expect(nextTaskStatus("done")).toBe("todo");
  });

  test("itemRoute sends each kind to its page, trades by symbol", () => {
    expect(itemRoute({ entity_type: "trade_group", id: 5 })).toBe(
      "/strategies?trade_group_id=5",
    );
    expect(itemRoute({ entity_type: "strategy", id: 2 })).toBe(
      "/strategies?strategy_id=2",
    );
    expect(itemRoute({ entity_type: "task", id: 1 })).toBe("/tasks");
    expect(
      itemRoute({ entity_type: "position", account_id: 1, con_id: 2 }),
    ).toBe("/positions");
    expect(
      itemRoute({ entity_type: "trade", id: 3, details: { symbol: "ES" } }),
    ).toBe("/trades?symbol=ES");
    expect(itemRoute({ entity_type: "live_execution", ib_exec_id: "x" })).toBe(
      "/trades",
    );
  });
});
