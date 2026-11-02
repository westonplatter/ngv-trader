// The rows of items matching the search under the current tab: a link to the
// item, a few details, and its tag chips.

import { Link } from "react-router-dom";
import { TagChipView } from "../TagChips";
import { formatWhen } from "../../lib/tagBrowser";
import { itemKey, itemRoute } from "../../lib/tags";
import type { TaggedItem } from "../../types/tags";

export default function TaggedItemsTable({ items }: { items: TaggedItem[] }) {
  return (
    <table className="min-w-full border-collapse text-sm">
      <tbody>
        {items.map((item) => (
          <tr key={itemKey(item)} className="border-b border-gray-100">
            <td className="whitespace-nowrap px-2 py-1.5 font-medium text-gray-800">
              <Link to={itemRoute(item)} className="hover:underline">
                {item.label}
              </Link>
              {item.entity_type === "live_execution" && (
                <span className="ml-1 rounded bg-amber-100 px-1 text-[10px] text-amber-800">
                  unsettled
                </span>
              )}
              {item.entity_type === "position" &&
                item.details.open === false && (
                  <span className="ml-1 rounded bg-gray-100 px-1 text-[10px] text-gray-600">
                    closed
                  </span>
                )}
            </td>
            <td className="whitespace-nowrap px-2 py-1.5 text-xs text-gray-500">
              {formatWhen(item.details.executed_at)}
              {typeof item.details.status === "string" && item.details.status}
              {typeof item.details.strategy === "string" &&
                ` · ${item.details.strategy}`}
            </td>
            <td className="px-2 py-1.5">
              <span className="inline-flex flex-wrap gap-1">
                {item.tags.map((chip) => (
                  <TagChipView key={chip.id} chip={chip} />
                ))}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
