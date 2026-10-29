import { describe, expect, test } from "bun:test";
import {
  DEMO_TASKS,
  demoTagList,
  demoTagSearch,
  demoTaskList,
  withPositionTags,
} from "./demoTags";
import { DEMO_POSITIONS } from "./demoData";

const search = (query: string) =>
  demoTagSearch(new URLSearchParams(query)).items.map((item) => item.label);

describe("demo tag fixtures", () => {
  test("one tag cuts across trade groups", () => {
    const labels = search("all=long-beta");
    expect(labels).toContain("NQ Sep'26 Future");
    expect(labels).toContain("MES Sep'26 Future");
    expect(labels).toContain("ES Jul'26 6000 Call");
  });

  test("all / any / none filter like the API", () => {
    expect(search("all=risk-off,offset-risk").sort()).toEqual(
      ["SPY Jul'26 540 Put", "SPY Protective Puts"].sort(),
    );
    expect(search("any=risk-off&none=offset-risk")).toEqual(["GLD Stock"]);
  });

  test("agent-applied chips are marked", () => {
    const spy = withPositionTags(DEMO_POSITIONS).find(
      (p) => p.con_id === 400000010,
    )!;
    expect(spy.tags!.find((c) => c.value === "offset-risk")!.created_by).toBe(
      "agent:local-llm",
    );
  });

  test("tasks hide done unless asked and are newest first", () => {
    const open = demoTaskList(new URLSearchParams());
    expect(open.every((t) => t.status !== "done")).toBe(true);
    expect(demoTaskList(new URLSearchParams("include_done=true"))).toHaveLength(
      DEMO_TASKS.length,
    );
    expect(open[0].created_at >= open[open.length - 1].created_at).toBe(true);
  });

  test("tag list is most-used first", () => {
    expect(demoTagList()[0].value).toBe("long-beta");
  });
});
