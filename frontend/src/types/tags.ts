// Free-form tags and tasks: API shapes shared by the Tags and Tasks pages,
// the inline chip editors, and the demo fixtures. The API client and helpers
// live in lib/tags.ts. See docs/design/tags-and-tasks.md.

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
