# Spec: Trade-Group YAML Meta ("management spec")

> **Status: PARTIAL — backend implemented (as of 2026-07-11).** The
> `trade_groups.meta_yaml` column, the parse/validate service
> (`src/services/trade_group_meta.py`), and the trade-groups API read/write path
> are live. A YAML editor in the tagging UI and agent consumption (comparing
> declared targets against live `latest_option_metrics`) are **not** built yet.

## Complexity: 2

One nullable column + migration, one small stateless parse/validate service, and
a few added fields on the existing trade-groups API models. No new tables, jobs,
or workers. Complexity is in the schema contract, not architectural surface.

## Purpose

A trade group today can carry only a `name`, free-text `notes`, and relational
tags. That is enough to *label* a campaign but not to *describe how it should be
managed*. The desk wants to attach a structured, human-authored "management spec"
to a group — target delta, estimated entry/exit dates, dated profit targets — so
that both the operator and an agent can read declared intent and steer an open
position against it.

## Problem

- `notes` is unstructured prose; nothing an agent can reliably parse.
- Tags are single normalized values, not structured documents. They cannot hold
  "target aggregate delta = 30, tolerance 5" or a list of dated profit targets.
- Position management intent lives in the operator's head. There is no place to
  record "for this GLD covered call I'm long 50 shares and want net delta ~30" so
  an agent can compare it to live greeks from TWS.

## Scope

- A single free-form YAML document attached per trade group.
- Raw source stored verbatim (comments/ordering preserved) so it round-trips.
- Light validation of a few **recognized** blocks so agents can rely on shape,
  with **arbitrary** keys passing through untouched.
- Read/write via the existing trade-groups API; parsed form exposed on detail.

## Non-goals

- No UI editor in this phase (edit via API / `meta_yaml` field).
- No agent logic that reads targets and compares them to live metrics yet.
- No per-key querying/indexing of meta (it is a document, not columns).
- No versioning/history of the meta document.
- No schema enforcement beyond the light recognized-block checks below.

## Current State

- `TradeGroup` (`src/models.py`) has `name`, `notes`, `status`, lifecycle
  timestamps. Structured attribution is relational via `tags`/`tag_links`.
- Live option greeks/delta per held `con_id` already land in
  `latest_option_metrics` (`option_metrics.sync.tws` job) and are surfaced on a
  group's open positions in `TradeGroupOpenPositionItem`.
- PyYAML is already a dependency (used by the OSI semantic loader).

## Desired Outcome

- An operator (or agent) can attach a YAML document to a trade group describing
  management intent, and read it back both raw and parsed.
- Recognized blocks have a documented, stable shape an agent can depend on.
- Malformed YAML or a malformed recognized block is rejected at write time, so a
  stored spec is always parseable.

## Recognized Schema

All keys optional. Unrecognized top-level keys are preserved as-is.

```yaml
# GLD covered call: long 50 shares, short 1 call. Steer net delta toward 30.
targets:
  delta:
    target: 30            # desired aggregate (static stock + transient options) delta
    min: 20
    max: 40
    tolerance: 5
    static: 50            # delta contributed by the 50 long shares
    options_transient: -20 # delta contributed by the short call (moves with the market)

dates:
  entry_estimate: 2026-07-15   # ISO YYYY-MM-DD
  exit_estimate: 2026-09-19

profit_targets:
  - date: 2026-08-15
    amount: 500
    note: take half off if realized+unrealized clears this
  - date: 2026-09-19
    amount: 1200

# arbitrary keys pass through untouched
thesis: gold consolidating; collect theta while range-bound
```

Validation rules (in `src/services/trade_group_meta.py`):

- Top level must be a YAML mapping (or empty → `None`).
- `targets` (if present) must be a mapping; `targets.delta` (if present) a
  mapping whose recognized numeric fields (`target`/`min`/`max`/`tolerance`/
  `static`/`options_transient`) must be numbers when set.
- `dates` (if present) must be a mapping; `entry_estimate`/`exit_estimate` must
  parse as ISO dates.
- `profit_targets` (if present) must be a list of mappings; each `date` an ISO
  date, each `amount` a number.
- Anything else passes through. Native YAML dates are normalized to ISO strings
  in the parsed output so it is JSON-serializable.

## Data Model and State Changes

- New nullable column `trade_groups.meta_yaml TEXT` (migration
  `a3bf4e84435e`). Additive, no backfill; existing groups read as `null`.
- No parsed/derived column — the parsed form is computed on read, keeping the raw
  source the single source of truth.

## API / Worker / Service Changes

- `src/services/trade_group_meta.py`: `parse_meta_yaml(raw) -> dict | None` +
  `TradeGroupMetaError`. Stateless; no DB or broker dependency.
- `POST /trade-groups`: accepts optional `meta_yaml`; validates (400 on
  malformed) and stores it.
- `PATCH /trade-groups/{id}`: accepts optional `meta_yaml`; validates and stores;
  a blank string clears the spec.
- `GET /trade-groups` and create/patch responses include raw `meta_yaml`.
- `GET /trade-groups/{id}` additionally returns parsed `meta` (JSON) for agents.
- No worker/job changes.

## Risks

- Schema drift: recognized-block shape is a soft contract; agents must tolerate
  missing/extra keys. Mitigated by keeping validation light and passthrough total.
- Free-form docs can grow unbounded; acceptable for a per-group text field.

## Acceptance Criteria

- Creating/patching a group with valid YAML persists `meta_yaml` verbatim.
- Invalid YAML or a malformed recognized block returns HTTP 400.
- `GET /trade-groups/{id}` returns `meta` as parsed JSON with dates as ISO
  strings and arbitrary keys preserved.
- Existing groups (no meta) return `meta_yaml: null`, `meta: null`.

## Follow-ups (future phases)

1. Tagging-UI YAML editor with inline validation + a recognized-schema hint.
2. Agent read path: compare `targets.delta` against the aggregate live delta
   derived from `latest_option_metrics` for the group's open positions, and flag
   drift / dated profit-target hits.

## Related Files

- `src/models.py` (`TradeGroup.meta_yaml`)
- `src/services/trade_group_meta.py`
- `src/api/routers/trade_groups.py`
- `alembic/versions/20260711015301_add_meta_yaml_to_trade_groups.py`
- `docs/trade-tagging.md`
