// The Trades / Positions / Trade groups / Tasks tabs above the results, each
// with the number of matching items.

import { TABS, type Tab } from "../../lib/tagBrowser";

export default function TagResultTabs({
  tab,
  counts,
  onSelect,
}: {
  tab: Tab;
  counts: Record<Tab, number>;
  onSelect: (tab: Tab) => void;
}) {
  return (
    <div className="flex gap-1 border-b border-gray-200">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onSelect(t.id)}
          className={`-mb-px border-b-2 px-3 py-1.5 text-sm ${
            tab === t.id
              ? "border-blue-600 font-medium text-blue-700"
              : "border-transparent text-gray-600 hover:text-gray-900"
          }`}
        >
          {t.label}{" "}
          <span className="text-xs text-gray-400">{counts[t.id]}</span>
        </button>
      ))}
    </div>
  );
}
