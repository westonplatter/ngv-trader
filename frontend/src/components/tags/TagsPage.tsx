// Tags page: the tag catalog (rename, recolor, merge, archive) and a search of
// tagged items by all / any / exclude, tabbed by kind. No P&L or other
// aggregates — tags are sticky notes, not a reporting dimension.
//
// This file only wires the two hooks to the panes. See docs/design/tags-and-tasks.md.

import { useMemo, useState } from "react";
import { countByTab, itemsForTab } from "../../lib/tagBrowser";
import TagCatalogPane from "./TagCatalogPane";
import TagFilterPanel from "./TagFilterPanel";
import TagResultTabs from "./TagResultTabs";
import TaggedItemsTable from "./TaggedItemsTable";
import { useTagCatalog } from "./useTagCatalog";
import { useTagSearch } from "./useTagSearch";

export default function TagsPage() {
  const [error, setError] = useState<string | null>(null);
  const catalog = useTagCatalog(setError);
  const search = useTagSearch(setError);

  const counts = useMemo(() => countByTab(search.items), [search.items]);
  const visible = itemsForTab(search.items, search.tab);

  return (
    <div className="flex h-full gap-4">
      <TagCatalogPane
        tags={catalog.tags}
        showArchived={catalog.showArchived}
        onShowArchived={catalog.setShowArchived}
        onCreate={catalog.create}
        selectedValue={search.all.length === 1 ? search.all[0] : null}
        onSelect={(tag) =>
          search.setParams({ all: [tag.normalized_value], any: [], none: [] })
        }
        onChanged={() => {
          catalog.reload();
          search.reload();
        }}
      />

      <section className="min-w-0 flex-1 space-y-3">
        <TagFilterPanel
          all={search.all}
          any={search.any}
          none={search.none}
          includeEnded={search.includeEnded}
          onChange={search.setParam}
          onIncludeEnded={search.setIncludeEnded}
        />

        {error && <p className="text-sm text-red-600">{error}</p>}

        <TagResultTabs
          tab={search.tab}
          counts={counts}
          onSelect={(tab) =>
            search.setParam("tab", tab === "trades" ? "" : tab)
          }
        />

        {!search.hasFilter ? (
          <p className="text-sm text-gray-500">
            Pick a tag on the left, or add tags to “All of” / “Any of”.
          </p>
        ) : visible.length === 0 ? (
          <p className="text-sm text-gray-500">Nothing here matches.</p>
        ) : (
          <TaggedItemsTable items={visible} />
        )}
      </section>
    </div>
  );
}
