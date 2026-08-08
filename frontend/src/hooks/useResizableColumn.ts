import { useCallback, useEffect, useRef, useState } from "react";

type UseResizableColumnOptions = {
  // localStorage key the chosen width is persisted under (device-specific layout
  // state, so localStorage rather than the server-side user-preferences API).
  storageKey: string;
  defaultWidth: number;
  minWidth: number;
  maxWidth: number;
};

export type ResizableColumn = {
  width: number;
  isDragging: boolean;
  // Bind to a divider element's onPointerDown to start a drag.
  onHandlePointerDown: (event: React.PointerEvent) => void;
  // Bind to onDoubleClick to snap the width back to its default.
  reset: () => void;
};

// Drives a draggable, persisted column width for a grid pane. The consumer feeds
// `width` into a CSS custom property on the grid's `grid-template-columns` track,
// so the pane resizes as the divider is dragged.
export function useResizableColumn({
  storageKey,
  defaultWidth,
  minWidth,
  maxWidth,
}: UseResizableColumnOptions): ResizableColumn {
  const clamp = useCallback(
    (w: number) => Math.min(maxWidth, Math.max(minWidth, w)),
    [minWidth, maxWidth],
  );

  const [width, setWidth] = useState<number>(() => {
    if (typeof window === "undefined") return defaultWidth;
    const stored = window.localStorage.getItem(storageKey);
    const parsed = stored != null ? Number.parseFloat(stored) : Number.NaN;
    return Number.isFinite(parsed) ? clamp(parsed) : defaultWidth;
  });

  const [isDragging, setIsDragging] = useState(false);
  // Drag origin captured on pointer-down; null when not dragging.
  const dragRef = useRef<{ startX: number; startWidth: number } | null>(null);

  const onHandlePointerDown = useCallback(
    (event: React.PointerEvent) => {
      // Left button only; ignore right/middle so context menus still work.
      if (event.button !== 0) return;
      event.preventDefault();
      dragRef.current = { startX: event.clientX, startWidth: width };
      setIsDragging(true);
    },
    [width],
  );

  const reset = useCallback(
    () => setWidth(defaultWidth),
    [defaultWidth],
  );

  useEffect(() => {
    if (!isDragging) return;

    const onPointerMove = (event: PointerEvent) => {
      const drag = dragRef.current;
      if (!drag) return;
      setWidth(clamp(drag.startWidth + (event.clientX - drag.startX)));
    };
    const endDrag = () => {
      dragRef.current = null;
      setIsDragging(false);
    };

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", endDrag);
    window.addEventListener("pointercancel", endDrag);
    // Suppress text selection and force the resize cursor for the whole drag.
    const prevUserSelect = document.body.style.userSelect;
    const prevCursor = document.body.style.cursor;
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", endDrag);
      window.removeEventListener("pointercancel", endDrag);
      document.body.style.userSelect = prevUserSelect;
      document.body.style.cursor = prevCursor;
    };
  }, [isDragging, clamp]);

  // Persist each settled width so the layout survives a reload.
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(storageKey, String(Math.round(width)));
  }, [storageKey, width]);

  return { width, isDragging, onHandlePointerDown, reset };
}
