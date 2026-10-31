// The small "AI" marker on anything an LLM agent created or applied, so a
// person can tell an agent's work from their own at a glance.

import { agentName, isAgent } from "../lib/tags";

export default function AgentBadge({
  createdBy,
  what = "Created",
  className = "",
}: {
  createdBy: string | null | undefined;
  // Verb for the tooltip: "Created by agent x" / "Applied by agent x".
  what?: string;
  className?: string;
}) {
  if (!isAgent(createdBy)) return null;
  return (
    <span
      className={`rounded bg-violet-100 px-1 text-[9px] font-semibold uppercase text-violet-700 ${className}`}
      title={`${what} by agent ${agentName(createdBy as string)}`}
      aria-label="agent"
    >
      AI
    </span>
  );
}
