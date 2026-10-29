// Free-form tags and tasks: types and API calls shared by the Tags and Tasks
// pages and the inline chip editors. See docs/design/tags-and-tasks.md.
//
// Tags are sticky notes. They never group items (that is trade groups) and never
// feed reporting (that is strategies).

import { API_BASE_URL } from "../config";

export type TagChip = {
  id: number;
  value: string;
  color: string | null;
  // "user", or "agent:<name>" when an LLM agent applied it.
  created_by: string;
  assigned_at: string;
  ended_at?: string | null;
};

export type Tag = {
  id: number;
  value: string;
  normalized_value: string;
  color: string | null;
  created_by: string;
  created_at: string;
  archived_at: string | null;
  usage: Record<string, number>;
};

export type TagEntityType =
  | "trade"
  | "live_execution"
  | "position"
  | "trade_group"
  | "task";

export type TaskEntityType =
  | "strategy"
  | "trade_group"
  | "position"
  | "trade"
  | "live_execution";

// One item, by its typed key: `id` for trades, trade groups, tasks, and
// strategies; account + contract for a position; the exec id for a live fill.
export type ItemRef = {
  entity_type: TagEntityType | TaskEntityType;
  id?: number | null;
  account_id?: number | null;
  con_id?: number | null;
  ib_exec_id?: string | null;
};

export type TaggedItem = ItemRef & {
  label: string;
  details: Record<string, unknown>;
  tags: TagChip[];
};

export type TaskStatus = "todo" | "in_progress" | "done";

export type TaskLink = ItemRef & {
  label: string;
  details: Record<string, unknown>;
  created_by: string;
};

export type Task = {
  id: number;
  title: string;
  notes: string | null;
  status: TaskStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  links: TaskLink[];
  tags: TagChip[];
};

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
};

export const TASK_STATUS_ORDER: TaskStatus[] = ["todo", "in_progress", "done"];

export function isAgent(createdBy: string | null | undefined): boolean {
  return Boolean(createdBy && createdBy.startsWith("agent:"));
}

export function agentName(createdBy: string): string {
  return createdBy.replace(/^agent:/, "");
}

// Same folding as the backend: case, spaces, dashes, and underscores.
export function normalizeTagValue(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s_-]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers:
      body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `${method} ${path} failed (${response.status})`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") detail = payload.detail;
    } catch {
      // keep the generic message
    }
    throw new Error(detail);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}

function query(
  params: Record<
    string,
    string | number | boolean | string[] | null | undefined
  >,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, v));
    else search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const tagsApi = {
  list: (q?: string, includeArchived = false) =>
    request<Tag[]>(
      "GET",
      `/tags${query({ q, include_archived: includeArchived || undefined })}`,
    ),
  create: (value: string, color?: string | null) =>
    request<Tag>("POST", "/tags", { value, color, created_by: "user" }),
  patch: (id: number, body: { value?: string; color?: string | null }) =>
    request<Tag>("PATCH", `/tags/${id}`, body),
  archive: (id: number) => request<Tag>("POST", `/tags/${id}/archive`),
  unarchive: (id: number) => request<Tag>("POST", `/tags/${id}/unarchive`),
  merge: (id: number, intoTagId: number) =>
    request<Tag>("POST", `/tags/${id}/merge`, { into_tag_id: intoTagId }),
  attach: (tags: (number | string)[], items: ItemRef[]) =>
    request<{ changed: number }>("POST", "/tag-links", {
      tags,
      items,
      created_by: "user",
    }),
  detach: (tags: (number | string)[], items: ItemRef[]) =>
    request<{ changed: number }>("DELETE", "/tag-links", {
      tags,
      items,
      created_by: "user",
    }),
  search: (params: {
    all?: string[];
    any?: string[];
    none?: string[];
    entityType?: TagEntityType;
    includeEnded?: boolean;
  }) =>
    request<{ items: TaggedItem[] }>(
      "GET",
      `/tags/search${query({
        all: params.all,
        any: params.any,
        none: params.none,
        entity_type: params.entityType,
        include_ended: params.includeEnded || undefined,
      })}`,
    ),
};

export const tasksApi = {
  list: (params: {
    status?: TaskStatus;
    includeDone?: boolean;
    tag?: string;
    strategyId?: number;
    tradeGroupId?: number;
    symbol?: string;
  }) =>
    request<Task[]>(
      "GET",
      `/tasks${query({
        status: params.status,
        include_done: params.includeDone || undefined,
        tag: params.tag,
        strategy_id: params.strategyId,
        trade_group_id: params.tradeGroupId,
        symbol: params.symbol,
      })}`,
    ),
  create: (body: {
    title: string;
    notes?: string | null;
    links?: ItemRef[];
    tags?: (number | string)[];
  }) => request<Task>("POST", "/tasks", { ...body, created_by: "user" }),
  patch: (
    id: number,
    body: { title?: string; notes?: string | null; status?: TaskStatus },
  ) => request<Task>("PATCH", `/tasks/${id}`, body),
  remove: (id: number) => request<void>("DELETE", `/tasks/${id}`),
  link: (id: number, items: ItemRef[]) =>
    request<Task>("POST", `/tasks/${id}/links`, { items, created_by: "user" }),
  unlink: (id: number, items: ItemRef[]) =>
    request<Task>("DELETE", `/tasks/${id}/links`, { items }),
};

// The item a trades-page row stands for: the trade once settled, else the live
// fill (which the API fans out to the whole order).
export function tradeRowItem(row: {
  settled?: boolean;
  trade_id: number | null;
  ib_exec_id: string;
}): ItemRef | null {
  if (row.settled === false)
    return { entity_type: "live_execution", ib_exec_id: row.ib_exec_id };
  return row.trade_id !== null
    ? { entity_type: "trade", id: row.trade_id }
    : null;
}
