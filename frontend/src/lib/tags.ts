// Free-form tags and tasks: API calls and helpers shared by the Tags and Tasks
// pages and the inline chip editors. Types are in ../types/tags. See
// docs/design/tags-and-tasks.md.
//
// Tags are sticky notes. They never group items (that is trade groups) and never
// feed reporting (that is strategies).

import { query, request } from "./api";
import type {
  ItemRef,
  Tag,
  TagEntityType,
  TaggedItem,
  Task,
  TaskStatus,
} from "../types/tags";

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
