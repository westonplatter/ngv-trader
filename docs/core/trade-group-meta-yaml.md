---
topics: ["trade-groups", "yaml-config", "meta", "agent-targeting"]
code_dirs_or_files:
  [
    "src/services/trade_group_meta.py",
    "src/models.py",
    "src/api/routers/trade_groups.py",
  ]
description: Free-form YAML management spec on trade groups — delta targets, dates, profit targets, and CRUD API surface.
---

# Trade-Group Meta (YAML)

An optional free-form YAML "management spec" attached to a trade group: target
delta, estimated entry/exit dates, dated profit targets — declared intent an
operator or agent can steer a position against.

## How it works

- Stored verbatim in `trade_groups.meta_yaml` (raw source round-trips; comments
  and ordering preserved).
- Recognized blocks are lightly validated so agents can rely on their shape;
  any other keys pass through untouched.
- Parsed to JSON on read (`GET /trade-groups/{id}` → `meta`); YAML-native dates
  become ISO strings.
- Malformed YAML or a malformed recognized block is rejected with **HTTP 400**.

## Recognized fields

All optional. Unknown top-level keys are preserved as-is.

| Field                                                | Shape                          | Meaning                                                             |
| ---------------------------------------------------- | ------------------------------ | ------------------------------------------------------------------- |
| `targets.delta.target` / `min` / `max` / `tolerance` | number                         | desired aggregate (static stock + transient options) delta and band |
| `targets.delta.static` / `options_transient`         | number                         | delta split: from shares vs. from options                           |
| `dates.entry_estimate` / `exit_estimate`             | ISO `YYYY-MM-DD`               | estimated lifecycle dates                                           |
| `profit_targets[]`                                   | list of `{date, amount, note}` | dated PnL checkpoints                                               |

```yaml
# GLD covered call: 200 long shares overwritten with calls. Steer net delta toward 120.
targets:
  delta:
    target: 120
    tolerance: 10
    static: 200 # from the 200 long shares
    options_transient: -80 # from the short calls, moves with the market
dates:
  entry_estimate: 2026-06-12
  exit_estimate: 2026-09-19
profit_targets:
  - date: 2026-08-15
    amount: 1500
    note: roll up calls if realized+unrealized clears this
thesis: gold consolidating; collect theta while range-bound # arbitrary passthrough
```

`src/services/trade_group_meta.py` is the validation source of truth.

## CRUD

`meta_yaml` is a field on the trade group — no dedicated endpoint.

| Op            | Call                                                                |
| ------------- | ------------------------------------------------------------------- |
| Create        | `POST /api/v1/trade-groups` with `meta_yaml`                        |
| Read (raw)    | `GET /api/v1/trade-groups` / create / patch responses → `meta_yaml` |
| Read (parsed) | `GET /api/v1/trade-groups/{id}` → `meta_yaml` **and** parsed `meta` |
| Update        | `PATCH /api/v1/trade-groups/{id}` with `meta_yaml`                  |
| Clear         | `PATCH /api/v1/trade-groups/{id}` with `meta_yaml: ""`              |

UI: the tagging group-detail panel renders `meta_yaml` read-only (collapsed
`Meta (YAML)` disclosure). **Edit** opens a monospace editor for it alongside
name/notes/status; saving an empty editor clears the spec. Server-side
validation errors (400) render inline under the form.

## Not yet built

Agent read path: compare `targets.delta` against the aggregate live delta from
`latest_option_metrics` for the group's open positions, and flag drift / dated
profit-target hits.

## Related

- `src/models.py` (`TradeGroup.meta_yaml`), `src/services/trade_group_meta.py`,
  `src/api/routers/trade_groups.py`
- [../trade-tagging.md](../trade-tagging.md) — trade groups, tags, assignment
