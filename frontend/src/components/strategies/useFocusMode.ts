// Focus mode collapses both list panes (Strategies + Trade Groups) so the
// selected group's detail fills the width. Persisted like privacy_mode so it
// survives reload. Toggled with the header button, `F`, or `Escape`.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";

const FOCUS_PREF_KEY = "trade_tagging_focus_mode";

export interface FocusMode {
  // Only collapse the panes when there is a detail to fill the space — a focus
  // toggle with nothing selected would hide both lists and leave an empty pane
  // with no way back to pick a group.
  focusActive: boolean;
  toggle: () => void;
}

export function useFocusMode(selectedGroupId: number | null): FocusMode {
  const [focusMode, setFocusMode] = useState(false);
  // Set once the user toggles focus mode. Guards against the async mount-time
  // preference GET clobbering a toggle the user made before it resolved.
  const touchedRef = useRef(false);
  // Chains preference PUTs so rapid toggles persist in order (last write wins).
  const writeChainRef = useRef<Promise<void>>(Promise.resolve());

  // Load the persisted preference once at mount. If the user has already
  // toggled by the time this resolves, their action wins.
  useEffect(() => {
    let active = true;
    api
      .get<{ value?: unknown } | null>(`/user-preferences/${FOCUS_PREF_KEY}`)
      .then((data) => {
        if (active && !touchedRef.current && data?.value === true) {
          setFocusMode(true);
        }
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  const toggle = useCallback(() => {
    touchedRef.current = true;
    setFocusMode((current) => {
      const next = !current;
      // Serialize writes so a slow earlier PUT can't land after a later one and
      // leave the persisted value out of sync with the last user action.
      writeChainRef.current = writeChainRef.current
        .catch(() => {})
        .then(() =>
          api
            .put(`/user-preferences/${FOCUS_PREF_KEY}`, { value: next })
            .then(() => undefined),
        );
      return next;
    });
  }, []);

  // Keyboard shortcuts: `F` toggles focus mode, `Escape` exits it. Ignore both
  // while typing in a form field so they don't hijack text entry.
  useEffect(() => {
    const isEditableTarget = (target: EventTarget | null): boolean => {
      if (!(target instanceof HTMLElement)) return false;
      const tag = target.tagName;
      return (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        tag === "SELECT" ||
        target.isContentEditable
      );
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isEditableTarget(event.target)) return;
      if (event.key === "Escape" && focusMode) {
        event.preventDefault();
        toggle();
      } else if ((event.key === "f" || event.key === "F") && !event.repeat) {
        // Only meaningful when a group is selected to fill the freed space.
        if (selectedGroupId == null) return;
        event.preventDefault();
        toggle();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [focusMode, selectedGroupId, toggle]);

  return { focusActive: focusMode && selectedGroupId != null, toggle };
}
