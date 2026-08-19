# Workflow at a glance

```mermaid
flowchart LR
  PRs["open bot PRs<br/>one package each"] --> T["triage_prs.py<br/>title → semver delta → tier"]
  T -->|low| L["chore/deps-&lt;eco&gt;-low"]
  T -->|medium| M["chore/deps-&lt;eco&gt;-medium"]
  T -->|high| H["leave the bot's PR open"]
  L --> B
  M --> B
  B["compare_baseline.py<br/>BEFORE any change"] --> BUMP["adapter add<br/>+ post_add_fixup"]
  BUMP --> CD["check_cooldown.py<br/>registry publish dates"]
  CD --> V["compare_baseline.py<br/>AFTER"]
  V -->|same or better| A["adapter audit_cmd<br/>report before/after"]
  V -->|any metric worse| X["fix or drop the package"]
  X --> BUMP
  A --> SHIP["commit + PR<br/>cite the counts"]
  SHIP --> CLOSE["merge → close superseded PRs"]
```

One branch per ecosystem per tier. Never mix tiers, never mix ecosystems.

## The baseline diff

```mermaid
flowchart LR
  BASE["origin/main<br/>detached worktree"] --> C1["adapter install + metrics"]
  WORK["working tree<br/>branch + bumps"] --> C2["adapter install + metrics"]
  C1 --> N1["base counts"]
  C2 --> N2["working counts"]
  N1 --> CMP{"compare<br/>per metric"}
  N2 --> CMP
  CMP -->|same or better| OK["ship, cite counts"]
  CMP -->|worse| NO["exit 1 — do not ship"]
```

Both sides run the identical commands the adapter declares; only the tree
differs. The bar is **unchanged**, not green — most repos do not gate every
check in CI, so some are already failing on the base branch.

Exception: if the batch bumps something in the adapter's `baseline_tools`, it
moved its own yardstick. Read the findings diff rather than the count.
