// Demo fixtures for free-form tags and tasks (see docs/design/tags-and-tasks.md).
//
// The story they tell is the one strategies and trade groups cannot: a tag cuts
// across groups. `long-beta` lands on NQ, MES, and ES rows that belong to three
// different trade groups; `offset-risk` was applied by an agent, so its chips
// carry the AI marker. Items are keyed exactly as the API keys them, and the
// fixtures reuse the existing demo positions, trades, and groups.

import type { Position } from "../types/positions";
import type { TradeExecutionRow } from "../types/trades";
import {
  DEMO_POSITIONS,
  DEMO_TRADE_EXECUTIONS,
  DEMO_TRADE_GROUPS,
} from "./demoData";
import type { ItemRef, Tag, TagChip, TaggedItem, Task, TaskLink } from "../types/tags";

const ACCOUNT_ID = 1;
const AGENT = "agent:local-llm";
const ASSIGNED_AT = "2026-06-21T13:05:00Z";

export const DEMO_TAGS: Tag[] = [
  {
    id: 1,
    value: "long-beta",
    normalized_value: "long-beta",
    color: "#2563eb",
    created_by: "user",
    created_at: "2026-06-01T00:00:00Z",
    archived_at: null,
    usage: {},
  },
  {
    id: 2,
    value: "risk-off",
    normalized_value: "risk-off",
    color: "#dc2626",
    created_by: "user",
    created_at: "2026-06-01T00:00:00Z",
    archived_at: null,
    usage: {},
  },
  {
    id: 3,
    value: "oil",
    normalized_value: "oil",
    color: "#a16207",
    created_by: "user",
    created_at: "2026-06-01T00:00:00Z",
    archived_at: null,
    usage: {},
  },
  {
    id: 4,
    value: "offset-risk",
    normalized_value: "offset-risk",
    color: "#7c3aed",
    created_by: AGENT,
    created_at: "2026-06-20T00:00:00Z",
    archived_at: null,
    usage: {},
  },
];

const position = (conId: number): ItemRef => ({
  entity_type: "position",
  account_id: ACCOUNT_ID,
  con_id: conId,
});
const trade = (id: number): ItemRef => ({ entity_type: "trade", id });
const group = (id: number): ItemRef => ({ entity_type: "trade_group", id });
const liveFill = (ibExecId: string): ItemRef => ({
  entity_type: "live_execution",
  ib_exec_id: ibExecId,
});
const task = (id: number): ItemRef => ({ entity_type: "task", id });

type Assignment = { tagId: number; item: ItemRef; createdBy?: string };

const ASSIGNMENTS: Assignment[] = [
  // long-beta: NQ, MES, and ES across three trade groups, settled and live.
  { tagId: 1, item: position(400000002) },
  { tagId: 1, item: position(400000009) },
  { tagId: 1, item: position(400000003) },
  { tagId: 1, item: trade(8001) },
  { tagId: 1, item: trade(8002) },
  { tagId: 1, item: liveFill("0000demo.00000004.01.01") },
  // risk-off: the SPY put hedge and the GLD stock.
  { tagId: 2, item: position(400000010) },
  { tagId: 2, item: position(756733) },
  { tagId: 2, item: group(105) },
  // oil: the CL roll and its future.
  { tagId: 3, item: group(107) },
  { tagId: 3, item: position(400000008) },
  // offset-risk: applied by a local agent on request.
  { tagId: 4, item: group(105), createdBy: AGENT },
  { tagId: 4, item: position(400000010), createdBy: AGENT },
  // Tags on tasks.
  { tagId: 3, item: task(1) },
  { tagId: 1, item: task(3), createdBy: AGENT },
];

function itemKey(item: ItemRef): string {
  if (item.entity_type === "position")
    return `position:${item.account_id}:${item.con_id}`;
  if (item.entity_type === "live_execution")
    return `live_execution:${item.ib_exec_id}`;
  return `${item.entity_type}:${item.id}`;
}

const tagById = new Map(DEMO_TAGS.map((tag) => [tag.id, tag]));

function chipsFor(item: ItemRef): TagChip[] {
  const key = itemKey(item);
  return ASSIGNMENTS.filter((a) => itemKey(a.item) === key).map((a) => {
    const tag = tagById.get(a.tagId)!;
    return {
      id: tag.id,
      value: tag.value,
      color: tag.color,
      created_by: a.createdBy ?? "user",
      assigned_at: ASSIGNED_AT,
    };
  });
}

const positionByConId = new Map(DEMO_POSITIONS.map((p) => [p.con_id, p]));
const groupById = new Map(DEMO_TRADE_GROUPS.map((g) => [g.id, g]));

function link(item: ItemRef, createdBy = "user"): TaskLink {
  const label =
    item.entity_type === "position"
      ? (positionByConId.get(item.con_id!)?.contract_display_name ??
        String(item.con_id))
      : item.entity_type === "trade_group"
        ? (groupById.get(item.id!)?.name ?? `Group ${item.id}`)
        : item.entity_type === "strategy"
          ? "core-book"
          : `Trade ${item.id}`;
  const details: Record<string, unknown> =
    item.entity_type === "position"
      ? { symbol: positionByConId.get(item.con_id!)?.symbol, open: true }
      : {};
  return { ...item, label, details, created_by: createdBy };
}

const BASE_TASKS: Omit<Task, "tags">[] = [
  {
    id: 1,
    title: "Roll CL before the Sep expiry",
    notes: "Calendar roll into Oct; check the spread before 14:00.",
    status: "in_progress",
    created_by: "user",
    created_at: "2026-06-20T15:00:00Z",
    updated_at: "2026-06-21T13:00:00Z",
    completed_at: null,
    links: [link(position(400000008)), link(group(107))],
  },
  {
    id: 2,
    title: "Cover the GLD 324 call if GLD closes above 320",
    notes: null,
    status: "todo",
    created_by: "user",
    created_at: "2026-06-21T12:00:00Z",
    updated_at: "2026-06-21T12:00:00Z",
    completed_at: null,
    links: [link(group(103)), link(position(400000007))],
  },
  {
    id: 3,
    title: "Trim long beta into CPI",
    notes: "NQ + MES + ES calls are ~1.4x beta. Suggested by the desk agent.",
    status: "todo",
    created_by: AGENT,
    created_at: "2026-06-21T13:10:00Z",
    updated_at: "2026-06-21T13:10:00Z",
    completed_at: null,
    links: [
      link({ entity_type: "strategy", id: 1 }, AGENT),
      link(position(400000002), AGENT),
      link(position(400000009), AGENT),
    ],
  },
  {
    id: 4,
    title: "Size the SPY put hedge",
    notes: null,
    status: "done",
    created_by: "user",
    created_at: "2026-06-18T14:00:00Z",
    updated_at: "2026-06-19T15:00:00Z",
    completed_at: "2026-06-19T15:00:00Z",
    links: [link(group(105))],
  },
];

export const DEMO_TASKS: Task[] = [...BASE_TASKS]
  .sort((a, b) => b.created_at.localeCompare(a.created_at))
  .map((t) => ({ ...t, tags: chipsFor(task(t.id)) }));

function openTaskCount(item: ItemRef): number {
  const key = itemKey(item);
  return DEMO_TASKS.filter(
    (t) => t.status !== "done" && t.links.some((l) => itemKey(l) === key),
  ).length;
}

// ── Row annotations (what the API adds to its read endpoints) ─────────────────

export function withPositionTags(rows: Position[]): Position[] {
  return rows.map((p) => {
    const item = position(p.con_id);
    return { ...p, tags: chipsFor(item), open_task_count: openTaskCount(item) };
  });
}

export function withTradeTags(rows: TradeExecutionRow[]): TradeExecutionRow[] {
  return rows.map((row) => {
    const item =
      row.settled === false
        ? liveFill(row.ib_exec_id)
        : row.trade_id !== null
          ? trade(row.trade_id)
          : null;
    return item
      ? { ...row, tags: chipsFor(item), open_task_count: openTaskCount(item) }
      : row;
  });
}

export function withGroupTags<T extends { id: number }>(
  row: T,
): T & { tags: TagChip[]; open_task_count: number } {
  return {
    ...row,
    tags: chipsFor(group(row.id)),
    open_task_count: openTaskCount(group(row.id)),
  };
}

// ── Endpoints ─────────────────────────────────────────────────────────────────

export function demoTagList(): Tag[] {
  return DEMO_TAGS.map((tag) => {
    const usage: Record<string, number> = {};
    for (const a of ASSIGNMENTS.filter((x) => x.tagId === tag.id))
      usage[a.item.entity_type] = (usage[a.item.entity_type] ?? 0) + 1;
    return { ...tag, usage };
  }).sort(
    (a, b) =>
      Object.values(b.usage).reduce((x, y) => x + y, 0) -
      Object.values(a.usage).reduce((x, y) => x + y, 0),
  );
}

function readList(params: URLSearchParams, key: string): Set<string> {
  return new Set(
    params
      .getAll(key)
      .flatMap((v) => v.split(","))
      .filter(Boolean),
  );
}

function describe(item: ItemRef): TaggedItem {
  const tags = chipsFor(item);
  if (item.entity_type === "position") {
    const p = positionByConId.get(item.con_id!);
    return {
      ...item,
      label: p?.contract_display_name ?? String(item.con_id),
      details: { symbol: p?.symbol, open: true },
      tags,
    };
  }
  if (item.entity_type === "trade_group") {
    const g = groupById.get(item.id!);
    return {
      ...item,
      label: g?.name ?? `Group ${item.id}`,
      details: { status: g?.status, strategy: g?.primary_strategy_value },
      tags,
    };
  }
  if (item.entity_type === "task") {
    const t = DEMO_TASKS.find((x) => x.id === item.id);
    return {
      ...item,
      label: t?.title ?? `Task ${item.id}`,
      details: { status: t?.status },
      tags,
    };
  }
  const row: TradeExecutionRow | undefined = DEMO_TRADE_EXECUTIONS.find((r) =>
    item.entity_type === "live_execution"
      ? r.ib_exec_id === item.ib_exec_id
      : r.trade_id === item.id,
  );
  const label = row
    ? `${row.side ?? ""} ${Math.abs(row.quantity)} ${row.trade_contract_display_name ?? row.contract_display ?? ""}`.trim()
    : `Trade ${item.id}`;
  return {
    ...item,
    label,
    details: {
      symbol: row?.contract_display?.split(" ")[0],
      executed_at: row?.executed_at,
    },
    tags,
  };
}

// Same all / any / none semantics as GET /tags/search.
export function demoTagSearch(params: URLSearchParams): {
  items: TaggedItem[];
} {
  const all = readList(params, "all");
  const any = readList(params, "any");
  const none = readList(params, "none");
  const items = new Map<string, ItemRef>();
  for (const a of ASSIGNMENTS) items.set(itemKey(a.item), a.item);
  const out: TaggedItem[] = [];
  for (const item of items.values()) {
    const values = new Set(chipsFor(item).map((c) => c.value));
    if ([...all].some((v) => !values.has(v))) continue;
    if (any.size > 0 && ![...any].some((v) => values.has(v))) continue;
    if ([...none].some((v) => values.has(v))) continue;
    out.push(describe(item));
  }
  return { items: out };
}

// Same filters as GET /tasks: done hidden unless asked for.
export function demoTaskList(params: URLSearchParams): Task[] {
  const status = params.get("status");
  const includeDone = params.get("include_done") === "true";
  const groupId = Number(params.get("trade_group_id")) || null;
  const tag = params.get("tag");
  return DEMO_TASKS.filter((t) =>
    status ? t.status === status : includeDone || t.status !== "done",
  )
    .filter(
      (t) =>
        groupId === null ||
        t.links.some(
          (l) => l.entity_type === "trade_group" && l.id === groupId,
        ),
    )
    .filter((t) => !tag || t.tags.some((c) => c.value === tag));
}
