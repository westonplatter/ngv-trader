# Spec: BAG Order Combo Visibility

## Purpose

Make combo/spread orders (`sec_type=BAG`) explicit in orders APIs and UI so a `BUY 1` wrapper order is not mistaken for directional single-leg exposure.

## Problem

- IBKR combo orders are represented as a BAG wrapper plus legs.
- Current `orders` persistence stores one contract/order shape only.
- Result: BAG orders can render as plain rows (`symbol=VIX`, `BUY 1`, etc.) without long/short leg context.
- Operators can misread spread risk and direction.

## Scope

- Persist BAG leg details alongside existing `orders` rows.
- Expose combo metadata and legs in API responses.
- Render combo/spread details in Orders UI.
- Preserve existing order lifecycle and worker behavior for non-BAG orders.

## Non-goals

- Replacing IBKR order submission flow.
- Reconstructing historical legs where broker data is unavailable.
- Implementing spread analytics or PnL attribution in this phase.

## Current-State Findings

- `orders` table/model has no normalized child rows for order legs.
- `order_sync` and worker logic capture wrapper contract fields (`con_id`, `local_symbol`, `contract_expiry`) but not BAG leg composition.
- API shape (`OrderResponse`) has no explicit combo fields.

## Proposed Design

### Data Model

Add an `order_legs` table:

- `id` (pk)
- `order_id` (fk to `orders.id`, not null)
- `leg_index` (int, not null)
- `con_id` (int, nullable)
- `symbol` (text, nullable)
- `sec_type` (text, nullable)
- `exchange` (text, nullable)
- `currency` (text, nullable)
- `local_symbol` (text, nullable)
- `trading_class` (text, nullable)
- `contract_expiry` (text, nullable)
- `ratio` (float, nullable)
- `action` (text, nullable)  
  Example: `BUY`/`SELL` at leg level.
- `raw` (jsonb/text-json, not null)
- `created_at`, `updated_at` (timestamptz, not null)

Constraints/indexes:

- Unique `(order_id, leg_index)`
- Index `(order_id)`
- Optional index `(con_id)` for lookup/debug

### Ingestion/Sync

Update both paths that observe broker trades:

- `src/services/order_sync.py`
- `scripts/work_order_queue.py` (trade progress path)

Behavior:

- Detect combo wrapper when `trade.contract.secType == "BAG"`.
- Extract `comboLegs` data (when present) and upsert `order_legs` rows.
- Replace legs snapshot per order update (delete+insert or deterministic upsert by `leg_index`).
- Persist full raw leg payload for drift tolerance.

Fallback behavior:

- If BAG has no leg payload from the API response, keep order flagged as BAG with empty legs and emit an order event message indicating missing leg detail.

### API

Extend `OrderResponse`:

- `is_combo: bool`
- `legs: list[OrderLegResponse]`
- `combo_summary: str | None`  
  Example: `+1 VIX Apr26 / -1 VIX May26`.

Add lightweight leg schema:

- `leg_index`, `action`, `ratio`, `con_id`, `local_symbol`, `contract_expiry`, `symbol`, `sec_type`

Compatibility:

- Keep existing fields unchanged.
- For non-BAG orders: `is_combo=false`, `legs=[]`, `combo_summary=null`.

### UI

Orders table changes:

- Show `Combo` badge when `is_combo=true` or `sec_type=BAG`.
- Replace ambiguous contract text with `combo_summary` when available.
- Row expand/click reveals leg table with direction and expiries.

Operator clarity requirements:

- A BAG `BUY 1` row must display at least one long and one short leg when leg data exists.
- Missing leg payload must be visually flagged as `Combo legs unavailable`.

## Migration and Backfill

1. Add Alembic migration for `order_legs`.
2. Add SQLAlchemy model and read relationship/lookup helpers.
3. No destructive backfill required.
4. Optional best-effort backfill job: re-sync recent broker orders and hydrate legs where still available.

## Rollout Plan

1. Migration + model.
2. Sync/worker leg ingestion.
3. API response extension.
4. Frontend rendering and combo badges.
5. Manual validation on known BAG order IDs.
6. Update runbook/docs for operator interpretation.

## Acceptance Criteria

- Known BAG order (example: VIX spread wrapper) appears as combo with explicit leg list.
- Orders endpoint returns stable `is_combo` and `legs` fields.
- Non-BAG orders are unchanged in behavior and payload meaning.
- Re-sync is idempotent (no duplicated legs per order).
- UI no longer presents BAG wrapper as ambiguous directional exposure.

## Risks and Mitigations

- IBKR payload inconsistency for combo legs.
  - Mitigation: persist raw payload + explicit missing-leg warnings.
- Partial historical visibility.
  - Mitigation: communicate best-effort backfill limits; keep forward correctness guaranteed.
- UI clutter.
  - Mitigation: default compact row with expandable leg details.

## Open Questions

- Should `combo_summary` be computed in API only, or stored denormalized on `orders` for query/sort efficiency?
- Do we need a dedicated filter (`combo_only=true`) in `/api/v1/orders` now or later?
- Should order events include per-leg fill progress in a later phase?
