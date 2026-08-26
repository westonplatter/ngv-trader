// Tests for the intraday/unsettled overlay added to the demo fixtures:
//   - two new all-live trade groups (MES Intraday Scalp, SPY Protective Puts)
//   - unsettled TWS fills mixed into otherwise-settled groups (NQ Momentum,
//     GLD Covered Calls)
//   - demoTradeGroupDetail / demoGroupExecutions merging settled openings
//     with unsettled fills and deriving marks_as_of from live data
import { describe, expect, test } from "bun:test";
import {
  DEMO_POSITIONS,
  DEMO_TRADE_GROUPS,
  demoGroupExecutions,
  demoTradeGroupDetail,
  demoTradeGroupRows,
} from "./demoData";

const GROUP_NQ_ID = 101;
const GROUP_ES_DIAGONAL_ID = 102;
const GROUP_GLD_CC_ID = 103;
const GROUP_MES_SCALP_ID = 104;
const GROUP_SPY_PUTS_ID = 105;
const UNKNOWN_GROUP_ID = 999999;

const LIVE_MARK_TS = "2026-06-21T14:29:55Z";
const SETTLED_AS_OF = "2026-06-21";

describe("DEMO_POSITIONS - new intraday live fixtures", () => {
  test("MES Intraday Scalp position (id 9) is live-only with no settled snapshot", () => {
    const pos = DEMO_POSITIONS.find((p) => p.id === 9);
    expect(pos).toBeDefined();
    expect(pos?.source).toBe("live");
    expect(pos?.mark_price).toBeNull();
    expect(pos?.position_value).toBeNull();
    expect(pos?.fifo_pnl_unrealized).toBeNull();
    expect(pos?.position).toBe(3);
    expect(pos?.avg_cost).toBe(5510.5);
    expect(pos?.mark).toBe(5514.75);
    expect(pos?.mark_ts).toBe(LIVE_MARK_TS);
    expect(pos?.live_unrealized).toBe(63.75);
    expect(pos?.trade_groups).toEqual([
      { id: GROUP_MES_SCALP_ID, name: "MES Intraday Scalp" },
    ]);
  });

  test("SPY Protective Puts position (id 10) is live-only with no settled snapshot", () => {
    const pos = DEMO_POSITIONS.find((p) => p.id === 10);
    expect(pos).toBeDefined();
    expect(pos?.source).toBe("live");
    expect(pos?.sec_type).toBe("OPT");
    expect(pos?.right).toBe("P");
    expect(pos?.mark_price).toBeNull();
    expect(pos?.position_value).toBeNull();
    expect(pos?.fifo_pnl_unrealized).toBeNull();
    expect(pos?.position).toBe(5);
    expect(pos?.avg_cost).toBe(385.0);
    expect(pos?.mark).toBe(4.1);
    expect(pos?.mark_ts).toBe(LIVE_MARK_TS);
    expect(pos?.live_unrealized).toBe(125.0);
    expect(pos?.trade_groups).toEqual([
      { id: GROUP_SPY_PUTS_ID, name: "SPY Protective Puts" },
    ]);
  });

  test("all live positions share the same intraday mark timestamp", () => {
    const liveTimestamps = DEMO_POSITIONS.filter(
      (p) => p.source === "live",
    ).map((p) => p.mark_ts);
    expect(liveTimestamps.length).toBeGreaterThan(0);
    for (const ts of liveTimestamps) {
      expect(ts).toBe(LIVE_MARK_TS);
    }
  });
});

describe("DEMO_TRADE_GROUPS - new intraday-only groups", () => {
  test("includes MES Intraday Scalp as an open group", () => {
    const group = DEMO_TRADE_GROUPS.find((g) => g.id === GROUP_MES_SCALP_ID);
    expect(group).toMatchObject({
      name: "MES Intraday Scalp",
      status: "open",
      closed_at: null,
    });
  });

  test("includes SPY Protective Puts as an open group", () => {
    const group = DEMO_TRADE_GROUPS.find((g) => g.id === GROUP_SPY_PUTS_ID);
    expect(group).toMatchObject({
      name: "SPY Protective Puts",
      status: "open",
      closed_at: null,
    });
  });
});

describe("demoTradeGroupDetail", () => {
  test("returns null for an unknown group id", () => {
    expect(demoTradeGroupDetail(UNKNOWN_GROUP_ID)).toBeNull();
  });

  test("NQ Momentum counts the settled opening plus its unsettled intraday fill", () => {
    const detail = demoTradeGroupDetail(GROUP_NQ_ID);
    expect(detail?.execution_count).toBe(2);
  });

  test("ES Call Diagonal (fully settled, no unsettled fills) counts only settled openings", () => {
    const detail = demoTradeGroupDetail(GROUP_ES_DIAGONAL_ID);
    expect(detail?.execution_count).toBe(2);
  });

  test("GLD Covered Calls counts all settled openings plus its unsettled intraday fill", () => {
    const detail = demoTradeGroupDetail(GROUP_GLD_CC_ID);
    expect(detail?.execution_count).toBe(5);
  });

  test("MES Intraday Scalp (all-live) counts only its unsettled fills, not a synthetic settled opening", () => {
    const detail = demoTradeGroupDetail(GROUP_MES_SCALP_ID);
    expect(detail?.execution_count).toBe(2);
  });

  test("SPY Protective Puts (all-live) counts only its single unsettled fill", () => {
    const detail = demoTradeGroupDetail(GROUP_SPY_PUTS_ID);
    expect(detail?.execution_count).toBe(1);
  });
});

describe("demoGroupExecutions", () => {
  test("returns null for an unknown group id", () => {
    expect(demoGroupExecutions(UNKNOWN_GROUP_ID)).toBeNull();
  });

  test("NQ Momentum: an unsettled fill alone flips marks_as_of to live even though unrealized pnl is unaffected", () => {
    const result = demoGroupExecutions(GROUP_NQ_ID);
    expect(result).not.toBeNull();
    expect(result?.executions).toHaveLength(2);

    const [settled, unsettled] = result!.executions;
    expect(settled.data_source).toBe("demo");
    expect(settled.settled).toBeUndefined();
    expect(unsettled).toMatchObject({
      id: 5101,
      data_source: "tws",
      settled: false,
      quantity: 1,
    });

    // No live_unrealized on this position, so intraday equals settled...
    expect(result?.total_unrealized_pnl).toBe(9615.0);
    expect(result?.intraday_unrealized_pnl).toBe(9615.0);
    expect(result?.intraday_total_pnl).toBe(9615.0);
    // ...but the presence of an unsettled execution alone flips marks_as_of.
    expect(result?.marks_as_of).toBe(LIVE_MARK_TS);
  });

  test("ES Call Diagonal: fully settled group (no live data at all) keeps the snapshot date", () => {
    const result = demoGroupExecutions(GROUP_ES_DIAGONAL_ID);
    expect(result?.executions).toHaveLength(2);
    expect(
      result?.executions.every(
        (e) => e.data_source === "demo" && e.settled === undefined,
      ),
    ).toBe(true);
    expect(result?.total_unrealized_pnl).toBe(2175.0); // 1000 + 1175
    expect(result?.intraday_unrealized_pnl).toBe(2175.0);
    expect(result?.intraday_total_pnl).toBe(2175.0);
    expect(result?.marks_as_of).toBe(SETTLED_AS_OF);
  });

  test("GLD Covered Calls: unsettled fill flips marks_as_of even though the fill contributes zero live_unrealized", () => {
    const result = demoGroupExecutions(GROUP_GLD_CC_ID);
    expect(result?.executions).toHaveLength(5);
    // Settled openings (ids 4-7) come first, in position order...
    expect(
      result?.executions.slice(0, 4).map((e) => e.contract_display),
    ).toEqual([
      "GLD Stock",
      "GLD Jul'26 311 Call",
      "GLD Jul'26 317 Call",
      "GLD Jul'26 324 Call",
    ]);
    // ...followed by the unsettled intraday fill.
    expect(result?.executions[4]).toMatchObject({
      id: 5103,
      data_source: "tws",
      settled: false,
    });

    expect(result?.total_unrealized_pnl).toBe(2572.0); // 2560 - 73 + 44 + 41
    expect(result?.intraday_unrealized_pnl).toBe(2572.0);
    expect(result?.intraday_total_pnl).toBe(2572.0);
    expect(result?.marks_as_of).toBe(LIVE_MARK_TS);
  });

  test("MES Intraday Scalp: all-live group excludes a synthetic settled opening for its live position", () => {
    const result = demoGroupExecutions(GROUP_MES_SCALP_ID);
    expect(result?.executions).toHaveLength(2);
    expect(
      result?.executions.every(
        (e) => e.data_source === "tws" && e.settled === false,
      ),
    ).toBe(true);
    // The unsettled fills' quantities sum to the live 3-lot position.
    expect(result?.executions.reduce((sum, e) => sum + e.quantity, 0)).toBe(3);

    expect(result?.open_positions).toHaveLength(1);
    expect(result?.open_positions[0].source).toBe("live");

    expect(result?.total_unrealized_pnl).toBe(0);
    expect(result?.intraday_unrealized_pnl).toBe(63.75);
    expect(result?.intraday_total_pnl).toBe(63.75);
    expect(result?.marks_as_of).toBe(LIVE_MARK_TS);
  });

  test("SPY Protective Puts: single unsettled fill matches the live 5-lot hedge position", () => {
    const result = demoGroupExecutions(GROUP_SPY_PUTS_ID);
    expect(result?.executions).toHaveLength(1);
    expect(result?.executions[0]).toMatchObject({
      quantity: 5,
      data_source: "tws",
      settled: false,
    });

    expect(result?.open_positions).toHaveLength(1);
    expect(result?.open_positions[0].source).toBe("live");

    expect(result?.total_unrealized_pnl).toBe(0);
    expect(result?.intraday_unrealized_pnl).toBe(125.0);
    expect(result?.intraday_total_pnl).toBe(125.0);
    expect(result?.marks_as_of).toBe(LIVE_MARK_TS);
  });
});
// ── Strategy P&L table fixtures (U5) ─────────────────────────────────────────

const GROUP_CL_CLOSED_ID = 106;
const GROUP_CL_ROLL_ID = 107;

describe("demoTradeGroupRows", () => {
  test("every fixture carries instruments and a boolean staleness flag", () => {
    for (const group of DEMO_TRADE_GROUPS) {
      expect(Array.isArray(group.instruments)).toBe(true);
      expect(group.instruments?.length).toBeGreaterThan(0);
      expect(typeof group.live_is_stale).toBe("boolean");
    }
  });

  test("the fixture set covers the states the table has to render", () => {
    expect(DEMO_TRADE_GROUPS.some((g) => g.status === "closed")).toBe(true);
    expect(
      DEMO_TRADE_GROUPS.some((g) => g.primary_strategy_value === null),
    ).toBe(true);
    expect(DEMO_TRADE_GROUPS.some((g) => g.live_is_stale)).toBe(true);
    expect(DEMO_TRADE_GROUPS.some((g) => g.instruments?.includes("CL"))).toBe(
      true,
    );
    expect(DEMO_TRADE_GROUPS.some((g) => !g.instruments?.includes("CL"))).toBe(
      true,
    );
  });

  test("an instrument pattern returns only the matching groups", () => {
    const rows = demoTradeGroupRows({ instrument: "CL.*", status: "all" });
    expect(rows.map((g) => g.id).sort()).toEqual([
      GROUP_CL_CLOSED_ID,
      GROUP_CL_ROLL_ID,
    ]);
  });

  test("the instrument pattern is case-insensitive and matches names too", () => {
    expect(demoTradeGroupRows({ instrument: "cl", status: "all" }).length).toBe(
      2,
    );
    expect(
      demoTradeGroupRows({ instrument: "Momentum", status: "all" }).map(
        (g) => g.id,
      ),
    ).toEqual([GROUP_NQ_ID]);
  });

  test("a malformed pattern matches nothing instead of throwing", () => {
    expect(demoTradeGroupRows({ instrument: "CL[", status: "all" })).toEqual(
      [],
    );
  });

  test("status=open excludes the closed fixture", () => {
    const ids = demoTradeGroupRows({ status: "open" }).map((g) => g.id);
    expect(ids).not.toContain(GROUP_CL_CLOSED_ID);
    expect(ids).toContain(GROUP_NQ_ID);
  });

  test("include_intraday=false leaves every overlay field null", () => {
    for (const group of demoTradeGroupRows({ status: "all" })) {
      expect(group.intraday_total_pnl).toBeNull();
      expect(group.intraday_realized_pnl).toBeNull();
      expect(group.intraday_unrealized_pnl).toBeNull();
      expect(group.realized_pnl).toBeNull();
      expect(group.unrealized_pnl).toBeNull();
      expect(group.marks_as_of).toBeNull();
      expect(group.live_is_stale).toBe(false);
      expect(group.instruments).toBeNull();
      // total_pnl is the pre-existing field and stays populated.
    }
    expect(
      demoTradeGroupRows({ status: "all" }).some((g) => g.total_pnl !== null),
    ).toBe(true);
  });

  test("a settled-only group reports no live mark", () => {
    const rows = demoTradeGroupRows({ status: "all", includeIntraday: true });
    expect(
      rows.find((g) => g.id === GROUP_ES_DIAGONAL_ID)?.marks_as_of,
    ).toBeNull();
    expect(rows.find((g) => g.id === GROUP_NQ_ID)?.marks_as_of).toBe(
      LIVE_MARK_TS,
    );
  });

  test("include_intraday=true populates the split from the detail helper", () => {
    const rows = demoTradeGroupRows({ status: "all", includeIntraday: true });
    const nq = rows.find((g) => g.id === GROUP_NQ_ID);
    const detail = demoGroupExecutions(GROUP_NQ_ID);

    expect(nq?.realized_pnl).toBe(detail?.total_realized_pnl ?? null);
    expect(nq?.unrealized_pnl).toBe(detail?.total_unrealized_pnl ?? null);
    expect(nq?.intraday_total_pnl).toBe(detail?.intraday_total_pnl ?? null);
    expect(nq?.marks_as_of).toBe(detail?.marks_as_of ?? null);
    expect(nq?.instruments).toEqual(["NQ"]);
  });

  test("the two CL fixtures carry their own figures (nothing is mapped to them)", () => {
    const rows = demoTradeGroupRows({ status: "all", includeIntraday: true });
    const closed = rows.find((g) => g.id === GROUP_CL_CLOSED_ID);
    expect(closed?.realized_pnl).toBe(4210.0);
    expect(closed?.unrealized_pnl).toBeNull();
    expect(closed?.intraday_total_pnl).toBe(4210.0);
    expect(closed?.primary_strategy_value).toBeNull();
  });

  test("a stale group keeps its own older mark timestamp", () => {
    const roll = demoTradeGroupRows({
      status: "all",
      includeIntraday: true,
    }).find((g) => g.id === GROUP_CL_ROLL_ID);
    expect(roll?.live_is_stale).toBe(true);
    expect(roll?.marks_as_of).toBe("2026-06-20T19:58:40Z");
  });

  test("the account filter narrows by account id", () => {
    expect(demoTradeGroupRows({ status: "all", accountId: "999" })).toEqual([]);
    expect(demoTradeGroupRows({ status: "all", accountId: "1" }).length).toBe(
      DEMO_TRADE_GROUPS.length,
    );
  });
});
