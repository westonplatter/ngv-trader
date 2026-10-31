// Saved structures in the sidebar: the list, which one is loaded, and the
// Save / Save As / Delete actions with their status line.

import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import type { SavedLeg, SavedStructure } from "../../types/pricing";

export type SaveStatus = "idle" | "pending" | "success" | "error";

export interface StructureBody {
  instrument: string;
  legs: SavedLeg[];
  spot_price: number | null;
}

export interface SavedStructures {
  structures: SavedStructure[];
  loadedId: number | null;
  status: SaveStatus;
  feedback: string | null;
  // Mark a structure as the loaded one and hand it back for the page to apply.
  select: (id: number) => SavedStructure | undefined;
  save: (body: StructureBody) => Promise<void>;
  saveAs: (name: string, body: StructureBody) => Promise<void>;
  remove: () => Promise<void>;
}

export function useSavedStructures(
  onError: (message: string) => void,
): SavedStructures {
  const [structures, setStructures] = useState<SavedStructure[]>([]);
  const [loadedId, setLoadedId] = useState<number | null>(null);
  const [status, setStatus] = useState<SaveStatus>("idle");
  const [feedback, setFeedback] = useState<string | null>(null);

  // Latest onError, read inside the async handlers so a changing callback
  // never retriggers the initial load.
  const onErrorRef = useRef(onError);
  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  const reload = useCallback(() => {
    api
      .get<SavedStructure[]>("/structures")
      .then(setStructures)
      .catch((err: unknown) =>
        onErrorRef.current(errorMessage(err, "Load failed")),
      );
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const select = useCallback(
    (id: number) => {
      const structure = structures.find((s) => s.id === id);
      if (!structure) return undefined;
      setStatus("idle");
      setFeedback(null);
      setLoadedId(structure.id);
      return structure;
    },
    [structures],
  );

  const save = useCallback(
    async (body: StructureBody) => {
      if (loadedId == null) return;
      setStatus("pending");
      setFeedback(null);
      try {
        await api.put(`/structures/${loadedId}`, {
          name: structures.find((s) => s.id === loadedId)?.name ?? "",
          ...body,
        });
        reload();
        setStatus("success");
        setFeedback(`Saved ${new Date().toLocaleTimeString()}`);
      } catch (err) {
        setStatus("error");
        setFeedback(`Save failed: ${errorMessage(err)}`);
      }
    },
    [loadedId, structures, reload],
  );

  const saveAs = useCallback(
    async (name: string, body: StructureBody) => {
      setStatus("idle");
      setFeedback(null);
      try {
        const created = await api.post<SavedStructure>("/structures", {
          name,
          ...body,
        });
        setLoadedId(created.id);
        reload();
      } catch {
        // a failed save-as leaves the sidebar untouched
      }
    },
    [reload],
  );

  const remove = useCallback(async () => {
    if (loadedId == null) return;
    await api.delete(`/structures/${loadedId}`);
    setStatus("idle");
    setFeedback(null);
    setLoadedId(null);
    reload();
  }, [loadedId, reload]);

  return { structures, loadedId, status, feedback, select, save, saveAs, remove };
}
