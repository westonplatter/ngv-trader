// The tag catalog in the sidebar: the sorted list (optionally with archived
// tags), a reload for after an edit, and creating a tag.

import { useCallback, useEffect, useState } from "react";
import { sortTagsByValue } from "../../lib/tagBrowser";
import { tagsApi } from "../../lib/tags";
import type { Tag } from "../../types/tags";

export interface TagCatalog {
  tags: Tag[];
  showArchived: boolean;
  setShowArchived: (show: boolean) => void;
  reload: () => void;
  create: (value: string) => void;
}

export function useTagCatalog(onError: (message: string) => void): TagCatalog {
  const [tags, setTags] = useState<Tag[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  // Bumped to refetch with the same filters.
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    tagsApi
      .list(undefined, showArchived)
      .then((rows) => {
        if (!cancelled) setTags(sortTagsByValue(rows));
      })
      .catch((err: Error) => {
        if (!cancelled) onError(err.message);
      });
    return () => {
      cancelled = true;
    };
  }, [showArchived, version, onError]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  const create = useCallback(
    (value: string) => {
      void tagsApi
        .create(value)
        .then(reload)
        .catch((err: Error) => onError(err.message));
    },
    [reload, onError],
  );

  return { tags, showArchived, setShowArchived, reload, create };
}
