// Demo mode lets the UI render static fixtures (see ./demoData) instead of
// hitting the live API. Useful for screenshots, design review, and trying out
// the app without a running backend.
//
// Enable it either way:
//   - URL query param:  ?demo=1  (or ?demo=true)
//   - Build-time env:    VITE_DEMO_MODE=1 in frontend/.env
//
// The URL param takes precedence so a single build can be toggled per-tab.

export function isDemoMode(): boolean {
  if (typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("demo");
    if (param !== null) {
      return param === "" || param === "1" || param.toLowerCase() === "true";
    }
  }
  const envFlag = import.meta.env.VITE_DEMO_MODE;
  return envFlag === "1" || envFlag === "true";
}
