# Client Portal Combo Spreads

## Purpose

Show CL calendar/time spreads using IBKR-native combo linkage from Client Portal API (CPAPI), instead of inferring spread relationships from independent legs.

## Why this exists

- TWS `reqPositions` / `ib.positions()` is leg-based.
- A combo spread can appear as unrelated positions unless native combo linkage is synced.
- Operators need both views:
  - spread-level view for monitoring intent and net exposure
  - leg-level view for execution and reconciliation

## Approach

Use a dual-source model:

- Source A: TWS positions for fast leg snapshots.
- Source B: CPAPI combo positions for native spread linkage.

UI behavior:

- Show CPAPI-linked spreads first.
- Show unmatched CL legs separately.

## Data and sync design

Store combo snapshots in dedicated spread tables:

- `combo_positions`
- `combo_position_legs`

Sync behavior:

- Authenticate CPAPI session.
- Read accounts from `/portfolio/accounts`.
- Fetch combos from `/portfolio/{accountId}/combo/positions?nocache=true`.
- Upsert combos and legs idempotently.
- Apply replace-style snapshot semantics per account.
- Keep full provider payload in `raw` for drift tolerance.

## API and UI expectations

Read endpoints:

- `GET /api/v1/spreads`
- `GET /api/v1/spreads/{spread_id}`
- `GET /api/v1/spreads/unmatched-legs`

UI expectations:

- Spread row with account, legs, net position, PnL, last sync.
- Expandable leg detail.
- Clear source badge: `Native Combo` vs `Unmatched Legs`.

## Ops notes

- CPAPI requires interactive login and periodic keepalive/re-auth.
- Session failures should be explicit and actionable (for example: re-auth required).
- TWS sync remains in place; this does not replace order placement flows.

## Rollout checklist

1. Add migrations and ORM models for combo tables.
2. Add CPAPI client and combo sync service.
3. Wire worker job for combo sync.
4. Add read API routes for spreads/unmatched legs.
5. Add frontend spread view/tab.
6. Document gateway login + re-auth workflow.

## Acceptance criteria

- Native IBKR combo positions appear as one spread with linked legs.
- Re-running sync remains idempotent.
- Session/auth failures are clear to operators.
- Existing `/positions` behavior stays unchanged.
- Spread view includes both native combos and unmatched CL legs.

## References

- IBKR CPAPI v1: <https://ibkrcampus.com/campus/ibkr-api-page/cpapi-v1/>
- IBKR Web API changelog: <https://ibkrcampus.com/campus/ibkr-api-page/web-api-changelog/>
- TWS complex positions guide: <https://ibkrguides.com/tws/usersguidebook/realtimeactivitymonitoring/complexpositions.htm>
- TWS API positions docs: <https://interactivebrokers.github.io/tws-api/positions.html>
- Flex complex positions report: <https://www.ibkrguides.com/reportingreference/reportguide/complexpositions_fq.htm>
