// Tailwind class strings for the bordered blue buttons repeated across pages.
// Plain constants, not a Button component: pages still pass them to a <button>
// (or <a>) themselves, and add layout classes next to them when they need to.

/** Standard bordered button: row and toolbar actions. */
export const OUTLINE_BUTTON =
  "rounded border border-blue-300 px-3 py-1 text-sm text-blue-700 hover:bg-blue-50 disabled:opacity-50";

/** Compact bordered button: actions inside table rows. */
export const OUTLINE_BUTTON_COMPACT =
  "rounded border border-blue-300 px-1.5 py-0.5 text-[11px] text-blue-700 hover:bg-blue-50 disabled:opacity-50";
