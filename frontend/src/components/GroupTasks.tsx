// Tasks section for a trade group: its open tasks with one-click status change,
// a quick add, and a link to the full list on the Tasks page.

import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  TASK_STATUS_LABEL,
  TASK_STATUS_ORDER,
  type Task,
  isAgent,
  tasksApi,
} from "../lib/tags";

export default function GroupTasks({ tradeGroupId }: { tradeGroupId: number }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    tasksApi
      .list({ tradeGroupId })
      .then(setTasks)
      .catch((err: Error) => setError(err.message));
  }, [tradeGroupId]);

  useEffect(() => load(), [load]);

  const run = async (action: () => Promise<unknown>) => {
    try {
      setError(null);
      await action();
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

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
          const next =
            TASK_STATUS_ORDER[
              (TASK_STATUS_ORDER.indexOf(task.status) + 1) %
                TASK_STATUS_ORDER.length
            ];
          return (
            <li key={task.id} className="flex items-center gap-2 text-sm">
              <button
                type="button"
                onClick={() =>
                  run(() => tasksApi.patch(task.id, { status: next }))
                }
                className="w-20 shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-[11px] text-gray-700 hover:bg-gray-200"
                title={`Move to ${TASK_STATUS_LABEL[next]}`}
              >
                {TASK_STATUS_LABEL[task.status]}
              </button>
              <span className="truncate text-gray-800">{task.title}</span>
              {isAgent(task.created_by) && (
                <span className="rounded bg-violet-100 px-1 text-[9px] font-semibold uppercase text-violet-700">
                  AI
                </span>
              )}
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
