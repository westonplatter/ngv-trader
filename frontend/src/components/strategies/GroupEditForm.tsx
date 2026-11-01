// The edit form for a trade group: name, notes, meta YAML, strategy, status.
// Owns its field state (seeded from the detail on mount) and sends only the
// fields that changed. Save errors surface inside the form rather than the
// page-level banner: a malformed-YAML 400 needs to be read next to the field
// that caused it.

import { useState } from "react";
import { errorMessage } from "../../lib/api";
import { GROUP_STATUSES, type GroupStatus } from "../../lib/strategies/groups";
import type { Strategy } from "../../types/strategies";
import type { TradeGroupDetail } from "../../types/tradeGroups";
import { statusClassName } from "./statusStyles";
import type { GroupPatch } from "./useTradeGroups";

// Shown as placeholder text in the empty meta editor, so the recognized blocks
// are discoverable without leaving the page. See docs/design/trade-group-meta-yaml.md.
const META_YAML_PLACEHOLDER = `targets:
  delta:
    target: 120
    tolerance: 10
dates:
  entry_estimate: 2026-06-12
  exit_estimate: 2026-09-19
profit_targets:
  - date: 2026-08-15
    amount: 1500
    note: roll up calls if this clears
thesis: arbitrary keys pass through`;

export default function GroupEditForm({
  detail,
  strategies,
  onSave,
  onCancel,
}: {
  detail: TradeGroupDetail;
  strategies: Strategy[];
  // Receives only the changed fields; an empty diff closes the form instead.
  onSave: (body: GroupPatch) => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState(detail.name);
  const [notes, setNotes] = useState(detail.notes ?? "");
  const [metaYaml, setMetaYaml] = useState(detail.meta_yaml ?? "");
  const [status, setStatus] = useState<GroupStatus>(detail.status);
  const [strategyId, setStrategyId] = useState<number | null>(
    detail.strategy_id ?? null,
  );
  const [error, setError] = useState<string | null>(null);

  const save = () => {
    setError(null);
    const body: GroupPatch = {};
    if (name.trim() !== detail.name) body.name = name.trim();
    if (notes !== (detail.notes ?? "")) body.notes = notes || null;
    // Send "" (not null) to clear: the API reads a null meta_yaml as "field not
    // provided" and only an empty string as an explicit clear.
    if (metaYaml !== (detail.meta_yaml ?? "")) body.meta_yaml = metaYaml;
    if (strategyId !== (detail.strategy_id ?? null)) {
      body.strategy_id = strategyId;
    }
    if (status !== detail.status) {
      body.status = status;
      if (status === "closed") {
        body.closed_by = "ui-trader";
        body.closed_at = new Date().toISOString();
      }
    }
    if (Object.keys(body).length === 0) {
      onCancel();
      return;
    }
    onSave(body).catch((err: unknown) =>
      setError(errorMessage(err, "Failed to save changes.")),
    );
  };

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold text-gray-900">
        Edit Trade Group #{detail.id}
      </h4>
      <div>
        <label className="mb-1 block text-xs text-gray-600">Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-gray-600">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
          rows={3}
        />
      </div>
      <div>
        <label className="mb-1 block text-xs text-gray-600">Meta (YAML)</label>
        <textarea
          value={metaYaml}
          onChange={(e) => setMetaYaml(e.target.value)}
          spellCheck={false}
          placeholder={META_YAML_PLACEHOLDER}
          className="w-full rounded border border-gray-300 px-2 py-1 font-mono text-xs leading-relaxed placeholder:text-gray-300"
          rows={10}
        />
        <p className="mt-1 text-xs text-gray-500">
          Optional management spec — <code>targets.delta</code>,{" "}
          <code>dates</code>, <code>profit_targets</code>. Other keys pass
          through. Leave empty to clear.
        </p>
      </div>
      <div>
        <label
          htmlFor="edit-group-strategy"
          className="mb-1 block text-xs text-gray-600"
        >
          Strategy
        </label>
        <select
          id="edit-group-strategy"
          value={strategyId ?? ""}
          onChange={(e) =>
            setStrategyId(e.target.value ? Number(e.target.value) : null)
          }
          className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
        >
          <option value="">No strategy</option>
          {/* The current strategy may be archived and hidden from the list. */}
          {detail.strategy_id != null &&
            !strategies.some(
              (strategy) => strategy.id === detail.strategy_id,
            ) && (
              <option value={detail.strategy_id}>
                {detail.primary_strategy_value ??
                  `Strategy #${detail.strategy_id}`}
              </option>
            )}
          {strategies.map((strategy) => (
            <option key={strategy.id} value={strategy.id}>
              {strategy.name}
              {strategy.archived_at ? " (archived)" : ""}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block text-xs text-gray-600">Status</label>
        <div className="flex gap-2">
          {GROUP_STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={`rounded border px-3 py-1 text-xs font-semibold uppercase ${
                status === s
                  ? statusClassName(s) + " border-current"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      {error && (
        <p className="rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          className="rounded border border-blue-300 px-4 py-1 text-sm text-blue-700 hover:bg-blue-50"
        >
          Save
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-gray-300 px-4 py-1 text-sm text-gray-600 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
