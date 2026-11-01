// Bulk tagging: one checkbox per order (the row that owns its group cell),
// and an add/remove tag action over the selection.

import { useCallback, useMemo, useState } from "react";
import { tagsApi, tradeRowItem } from "../../lib/tags";
import { rowGroupKey } from "../../lib/trades/view";
import type { ItemRef } from "../../types/tags";
import type { TradeExecutionRow } from "../../types/trades";

export interface BulkTagging {
  selectedKeys: Set<string>;
  // Group keys that can be selected in the current view.
  selectableKeys: string[];
  allSelected: boolean;
  message: string | null;
  toggle: (key: string) => void;
  selectAll: (checked: boolean) => void;
  clear: () => void;
  apply: (mode: "add" | "remove", value: string) => Promise<void>;
}

export function useBulkTagging(
  rows: TradeExecutionRow[],
  owners: Map<string, number>,
  onChanged: () => void,
): BulkTagging {
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);

  const itemByGroupKey = useMemo(() => {
    const map = new Map<string, ItemRef>();
    for (const row of rows) {
      const key = rowGroupKey(row);
      if (owners.get(key) !== row.id) continue;
      const item = tradeRowItem(row);
      if (item) map.set(key, item);
    }
    return map;
  }, [rows, owners]);
  const selectableKeys = useMemo(
    () => Array.from(itemByGroupKey.keys()),
    [itemByGroupKey],
  );
  const allSelected =
    selectableKeys.length > 0 &&
    selectableKeys.every((key) => selectedKeys.has(key));

  const toggle = useCallback(
    (key: string) =>
      setSelectedKeys((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      }),
    [],
  );
  const selectAll = useCallback(
    (checked: boolean) =>
      setSelectedKeys(checked ? new Set(selectableKeys) : new Set()),
    [selectableKeys],
  );
  const clear = useCallback(() => setSelectedKeys(new Set()), []);

  const apply = useCallback(
    async (mode: "add" | "remove", value: string) => {
      const items = Array.from(selectedKeys)
        .map((key) => itemByGroupKey.get(key))
        .filter((item): item is ItemRef => item !== undefined);
      if (items.length === 0) return;
      try {
        const result =
          mode === "add"
            ? await tagsApi.attach([value], items)
            : await tagsApi.detach([value], items);
        setMessage(
          `${mode === "add" ? "Tagged" : "Untagged"} ${result.changed} item${result.changed === 1 ? "" : "s"}.`,
        );
        onChanged();
      } catch (err) {
        setMessage(err instanceof Error ? err.message : String(err));
      }
    },
    [selectedKeys, itemByGroupKey, onChanged],
  );

  return {
    selectedKeys,
    selectableKeys,
    allSelected,
    message,
    toggle,
    selectAll,
    clear,
    apply,
  };
}
