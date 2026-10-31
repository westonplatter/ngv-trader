// Tasks section for a trade group: its open tasks with one-click status change,
// a quick add, and a link to the full list on the Tasks page.

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AgentBadge from "./AgentBadge";
import { useAsyncAction } from "../hooks/useAsyncAction";
import {
  TASK_STATUS_LABEL,
  type Task,
  nextTaskStatus,
  tasksApi,
} from "../lib/tags";

export default function GroupTasks({
  tradeGroupId,
  onChanged,
}: {
  tradeGroupId: number;
  // Lets the page refresh what shows open-task counts (the group list).
  onChanged?: () => void;
}) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    tasksApi
      .list({ tradeGroupId })
      .then(setTasks)
      .catch((err: Error) => setLoadError(err.message));
  }, [tradeGroupId]);

  useEffect(() => load(), [load]);

  const {
    run,
    error: actionError,
    pending,
  } = useAsyncAction(() => {
    load();
    onChanged?.();
  });
  const error = actionError ?? loadError;

  return (
    <div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">Tasks</span>
        <Link
          to={`/tasks?trade_group_id=${tradeGroupId}`}
          className="text-xs text-blue-600 hover:underline"
        >
          All tasks
        </Link>
      </div>
      <ul className="mt-1 space-y-1">
        {tasks.map((task) => {
          const next = nextTaskStatus(task.status);
          return (
            <li key={task.id} className="flex items-center gap-2 text-sm">
              <button
                type="button"
                onClick={() =>
                  run(() => tasksApi.patch(task.id, { status: next }))
                }
                disabled={pending}
                className="w-20 shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-200 disabled:opacity-50"
                title={`Move to ${TASK_STATUS_LABEL[next]}`}
              >
                {TASK_STATUS_LABEL[task.status]}
              </button>
              <span className="truncate text-gray-800">{task.title}</span>
              <AgentBadge createdBy={task.created_by} />
            </li>
          );
        })}
      </ul>
      <input
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && title.trim())
            void run(async () => {
              await tasksApi.create({
                title: title.trim(),
                links: [{ entity_type: "trade_group", id: tradeGroupId }],
              });
              setTitle("");
            });
        }}
        placeholder="+ task for this group (Enter)"
        className="mt-1 w-full rounded border border-gray-200 px-2 py-1 text-xs"
      />
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}
