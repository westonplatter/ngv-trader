// Tasks page: simple to-dos (To do → In progress → Done) linked to strategies,
// trade groups, positions, and trades. Newest first; done tasks sit behind a
// toggle and are never deleted automatically.

import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AgentBadge from "./AgentBadge";
import TagChips from "./TagChips";
import { useAsyncAction } from "../hooks/useAsyncAction";
import { errorMessage } from "../lib/api";
import {
  TASK_STATUS_LABEL,
  TASK_STATUS_ORDER,
  itemKey,
  itemRoute,
  nextTaskStatus,
  tasksApi,
} from "../lib/tags";
import type { Task, TaskStatus } from "../types/tags";

const STATUS_CLASS: Record<TaskStatus, string> = {
  todo: "bg-gray-100 text-gray-800",
  in_progress: "bg-blue-100 text-blue-800",
  done: "bg-emerald-100 text-emerald-800",
};

const LINK_KIND: Record<string, string> = {
  strategy: "Strategy",
  trade_group: "Group",
  position: "Position",
  trade: "Trade",
  live_execution: "Trade",
};

function TaskRow({ task, onChanged }: { task: Task; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(task.title);
  const [notes, setNotes] = useState(task.notes ?? "");
  const { run, error, pending } = useAsyncAction(onChanged);
  const nextStatus = nextTaskStatus(task.status);

  return (
    <li className="space-y-1.5 rounded border border-gray-200 bg-white p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="space-y-1.5">
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
              />
              <textarea
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
                rows={3}
                className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                placeholder="Notes"
              />
              <div className="flex gap-2 text-xs">
                <button
                  type="button"
                  onClick={() =>
                    run(async () => {
                      await tasksApi.patch(task.id, {
                        title,
                        notes: notes || null,
                      });
                      setEditing(false);
                    })
                  }
                  className="rounded bg-gray-900 px-2 py-0.5 text-white"
                >
                  Save
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="underline"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : (
            <>
              <p
                className={`text-sm font-medium ${task.status === "done" ? "text-gray-400 line-through" : "text-gray-900"}`}
              >
                {task.title}
                <AgentBadge
                  createdBy={task.created_by}
                  className="ml-1.5 align-middle"
                />
              </p>
              {task.notes && (
                <p className="whitespace-pre-wrap text-xs text-gray-600">
                  {task.notes}
                </p>
              )}
            </>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 text-xs">
          <button
            type="button"
            onClick={() =>
              run(() => tasksApi.patch(task.id, { status: nextStatus }))
            }
            disabled={pending}
            className={`rounded px-2 py-0.5 font-medium disabled:opacity-50 ${STATUS_CLASS[task.status]}`}
            title={`Move to ${TASK_STATUS_LABEL[nextStatus]}`}
          >
            {TASK_STATUS_LABEL[task.status]}
          </button>
          {task.status !== "done" && (
            <button
              type="button"
              onClick={() =>
                run(() => tasksApi.patch(task.id, { status: "done" }))
              }
              disabled={pending}
              className="text-emerald-700 hover:underline disabled:opacity-50"
            >
              Done
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              // Start from the task as it is now (an agent may have edited it).
              setTitle(task.title);
              setNotes(task.notes ?? "");
              setEditing(true);
            }}
            className="text-gray-500 hover:underline"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() =>
              window.confirm(`Delete "${task.title}"?`) &&
              run(() => tasksApi.remove(task.id))
            }
            className="text-gray-400 hover:text-red-600"
          >
            Delete
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        {task.links.map((link) => {
          const closed =
            link.entity_type === "position" && link.details.open === false;
          return (
            <span
              key={itemKey(link)}
              className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-slate-700"
            >
              <span className="text-[10px] uppercase text-slate-500">
                {LINK_KIND[link.entity_type]}
              </span>
              <Link to={itemRoute(link)} className="hover:underline">
                {link.label}
              </Link>
              {closed && (
                <span className="text-[10px] text-gray-500">(closed)</span>
              )}
              <button
                type="button"
                onClick={() => run(() => tasksApi.unlink(task.id, [link]))}
                className="text-slate-400 hover:text-red-600"
                aria-label={`Unlink ${link.label}`}
              >
                ×
              </button>
            </span>
          );
        })}
        <TagChips
          item={{ entity_type: "task", id: task.id }}
          tags={task.tags}
          onChanged={onChanged}
        />
        <span className="ml-auto text-[11px] text-gray-400">
          {new Date(task.created_at).toLocaleDateString()}
        </span>
      </div>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </li>
  );
}

export default function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [newTitle, setNewTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const status = (searchParams.get("status") as TaskStatus | null) ?? undefined;
  const showDone = searchParams.get("done") === "1";
  const tag = searchParams.get("tag") ?? "";
  const symbol = searchParams.get("symbol") ?? "";
  const strategyId = Number(searchParams.get("strategy_id")) || undefined;
  const tradeGroupId = Number(searchParams.get("trade_group_id")) || undefined;

  // One update for several keys: react-router does not chain functional
  // setSearchParams updates made in the same tick, so the last would win.
  const setParams = (updates: Record<string, string>) =>
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(updates)) {
          if (value) next.set(key, value);
          else next.delete(key);
        }
        return next;
      },
      { replace: true },
    );
  const setParam = (key: string, value: string) => setParams({ [key]: value });

  // Filters reload on every keystroke; only the latest request may land.
  const requestSeq = useRef(0);
  const load = useCallback(() => {
    const seq = ++requestSeq.current;
    tasksApi
      .list({
        status,
        includeDone: showDone,
        tag: tag || undefined,
        symbol: symbol || undefined,
        strategyId,
        tradeGroupId,
      })
      .then((rows) => {
        if (seq !== requestSeq.current) return;
        setTasks(rows);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [status, showDone, tag, symbol, strategyId, tradeGroupId]);

  useEffect(() => load(), [load]);

  const create = async () => {
    if (!newTitle.trim()) return;
    const links = [
      ...(strategyId
        ? [{ entity_type: "strategy" as const, id: strategyId }]
        : []),
      ...(tradeGroupId
        ? [{ entity_type: "trade_group" as const, id: tradeGroupId }]
        : []),
    ];
    try {
      await tasksApi.create({
        title: newTitle.trim(),
        links,
        tags: tag ? [tag] : [],
      });
      setNewTitle("");
      load();
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-3">
      <div className="flex flex-wrap items-center gap-3 rounded border border-gray-200 bg-white p-3 text-xs">
        <select
          value={status ?? ""}
          onChange={(event) => setParam("status", event.target.value)}
          className="rounded border border-gray-300 px-1.5 py-1"
          aria-label="Status"
        >
          <option value="">Open (to do + in progress)</option>
          {TASK_STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {TASK_STATUS_LABEL[s]}
            </option>
          ))}
        </select>
        <input
          value={tag}
          onChange={(event) => setParam("tag", event.target.value)}
          placeholder="Tag"
          className="w-28 rounded border border-gray-300 px-1.5 py-1"
        />
        <input
          value={symbol}
          onChange={(event) => setParam("symbol", event.target.value)}
          placeholder="Symbol"
          className="w-24 rounded border border-gray-300 px-1.5 py-1"
        />
        {(strategyId || tradeGroupId) && (
          <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5">
            {strategyId ? `Strategy #${strategyId}` : `Group #${tradeGroupId}`}
            <button
              type="button"
              onClick={() => setParams({ strategy_id: "", trade_group_id: "" })}
              className="text-slate-400 hover:text-red-600"
              aria-label="Clear"
            >
              ×
            </button>
          </span>
        )}
        <label className="ml-auto flex items-center gap-1 text-gray-600">
          <input
            type="checkbox"
            checked={showDone}
            onChange={(event) =>
              setParam("done", event.target.checked ? "1" : "")
            }
          />
          Show done
        </label>
      </div>

      <div className="flex gap-2">
        <input
          value={newTitle}
          onChange={(event) => setNewTitle(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && void create()}
          placeholder="New task…  (Enter to add)"
          className="flex-1 rounded border border-gray-300 px-2 py-1.5 text-sm"
        />
        <button
          type="button"
          onClick={() => void create()}
          className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white"
        >
          Add
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {tasks.length === 0 ? (
        <p className="text-sm text-gray-500">No tasks.</p>
      ) : (
        <ul className="space-y-2">
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} onChanged={load} />
          ))}
        </ul>
      )}
    </div>
  );
}
