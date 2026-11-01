// Status colors shared by the group list badges, section headers, and the
// detail header.

import type { GroupStatus } from "../../lib/strategies/groups";

export function statusClassName(status: GroupStatus): string {
  if (status === "open") return "bg-emerald-100 text-emerald-800";
  if (status === "closed") return "bg-gray-100 text-gray-700";
  return "bg-amber-100 text-amber-800";
}

// Text color for the section headers (Open / Closed / Archived), keyed to the
// same palette as the per-group status badges.
export function statusHeaderClassName(status: GroupStatus): string {
  if (status === "open") return "text-emerald-700";
  if (status === "closed") return "text-gray-600";
  return "text-amber-700";
}

// Sign-colored P&L text, with the muted class for an unknown value.
export function pnlClassName(value: number | null): string {
  if (value == null) return "text-gray-500";
  return value >= 0
    ? "font-semibold text-emerald-700"
    : "font-semibold text-red-700";
}

export function formatUsd(value: number | null): string {
  if (value == null) return "—";
  return value.toLocaleString(undefined, { style: "currency", currency: "USD" });
}
