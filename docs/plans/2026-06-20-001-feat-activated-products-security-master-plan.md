---
title: "feat: Activated products and security master sync"
type: feat
status: partial
created: 2026-06-20
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: migrated-spec
execution: code
depth: standard
---

# feat: Activated products and security master sync

> **Implementation status (verified 2026-10-10): shipped except U7.** The
> `activated_products` table (seeded CL/NG/ZB/ZN/ES/NQ), IBKR discovery and the
> 12-month sync, the `contracts.sync_activated` job, `GET /api/v1/activated-products`,
> the `list_activated_products` agent tool, and the Active Products table in
> `MarketDataPage.tsx` are live. **Remaining:** `resolve_exchange()` in
> `src/data/exchanges.py` still raises for unknown futures symbols.

## Goal Capsule

- **Objective:** An operator declares a small set of futures products and the system keeps the next 12 calendar months of each in `contracts`, so the tradebot resolves `con_id`s from the DB instead of IBKR. This is the foundation for multi-leg trades (e.g. a calendar butterfly).
- **Authority hierarchy:** IBKR `reqContractDetails` is authoritative for exchange and metadata; `contracts` is the local security master. The agent never talks to IBKR directly.
- **Execution profile:** Migration → discovery + sync → job → API + agent tool → UI → demote `resolve_exchange`.
- **Stop conditions:** Stop if demoting `resolve_exchange` would change the result for any symbol already in the map.
- **Tail ownership:** Standard repo flow.

---

## Product Contract

### Summary

A curated `activated_products` table, discovery from symbol alone, a 12-calendar-month FUT window per product, an on-demand job, a read API, an agent tool, and a read-only UI listing.

### Problem Frame

- There was no persisted notion of which products we maintain; contract sync was ad hoc.
- A plain `FUT` sync upserted every expiry with no calendar window.
- Exchange came from a hardcoded map, so a new product needed a code change and unknown symbols raised.
- No UI showed what was activated, its exchange, or whether it was synced.

### Requirements

- R1. `activated_products` exists, seeded with CL, NG, ZB, ZN, ES, NQ.
- R2. A product added by symbol alone gets exchange and metadata discovered from IBKR and becomes `active`.
- R3. Sync writes only FUT contracts expiring within the next `months_ahead` (default 12) calendar months and deactivates that product's contracts outside the window.
- R4. Ambiguous or unknown symbols surface `needs_disambiguation` / `unknown_symbol` and `last_error`, never a silent guess.
- R5. `GET /api/v1/activated-products` returns rows with a correct `security_master_count`.
- R6. The market-data page shows an Active Products table: symbol, sec_type, exchange (or "discovering…"), status badge, multiplier, contract count, last-synced age.
- R7. `list_activated_products` and `lookup_contract` let the LLM resolve `con_id` per month for every activated product without touching IBKR.
- R8. Unknown symbols flow through IBKR discovery instead of raising in `resolve_exchange()`.

### Non-Goals

- Multi-leg spread construction, preview, or routing.
- FOP/OPT chain sync for activated products.
- Add/edit/delete or disambiguation UI (rows are seeded and editable via DB/API).

---

## Planning Contract

### Key Technical Decisions

KTD1. **One `reqContractDetails` call per product.** `Future(symbol, currency=...)` with no exchange returns both the exchange and the contract list.

KTD2. **Exactly one distinct exchange → use it; multiple → `needs_disambiguation`; zero → `unknown_symbol`.**

KTD3. **The window is computed at sync time,** so reruns roll it forward and retire expired contracts.

KTD4. **Demote, don't delete, `resolve_exchange`.** Keep returning map values for known symbols; stop raising only at the new call sites.

Data model and state machine (`pending` → `active` | `needs_disambiguation` | `unknown_symbol`) are as shipped in `ActivatedProduct` (`src/models.py`).

---

## Implementation Units

### U1–U6. Table, discovery, sync, job, API + tool, UI ✅ shipped

**Requirements:** R1–R7

**Files:** `src/models.py`, `alembic/versions/`, `src/services/contract_sync.py` (`discover_product_metadata`, `sync_activated_products`), `src/services/jobs.py`, `src/workers/jobs.py` (`handle_contracts_sync_activated`), `src/api/routers/activated_products.py`, `src/services/tradebot_agent.py`, `frontend/src/components/MarketDataPage.tsx`

### U7. Demote `resolve_exchange()` to a hint

**Requirements:** R8, KTD4

**Files:** `src/data/exchanges.py`, `src/services/contract_lookup.py`, `src/services/tradebot_agent.py`

**Approach:** Return `None` (or a sentinel) for unknown futures symbols instead of raising, and have callers fall back to IBKR discovery.

**Test scenarios:**

- Known symbols still return their mapped exchange.
- An unknown futures symbol no longer raises; the caller routes to discovery.
- Non-futures behavior (`SMART`) is unchanged.

---

## Verification Contract

| Gate          | Command                          | Applies to |
| ------------- | -------------------------------- | ---------- |
| Imports       | `uv run python scripts/check.py` | U7         |
| Backend tests | `task test -- -k exchange`       | U7         |

---

## Definition of Done

- All R1–R7 hold (shipped).
- `resolve_exchange()` no longer raises for unknown futures symbols, and existing callers behave the same for known ones.
- On ship, fold this into a current-state doc (e.g. `docs/security-data.md`) per the docs conventions.

---

## Risks & Dependencies

- A symbol may resolve to an unexpected exchange; `needs_disambiguation` covers the multi-exchange case.
- `resolve_exchange` has several callers; KTD4 keeps their known-symbol behavior.

---

## Open Questions

- Should add-product and disambiguation become UI actions, or stay DB/API-only?
- Should sync run on a schedule or stay on-demand until the spread feature lands? (Overlaps with the freshness unit in [the tradebot auto-fetch plan](2026-02-25-001-feat-tradebot-contract-metadata-autofetch-plan.md).)

---

## Sources & Research

- `src/services/contract_sync.py`, `src/data/exchanges.py`, `src/services/contract_lookup.py`.
- `docs/workers.md`, `docs/tradebot-chatbot.md`.
- Migrated from `docs/spec-activated-products-security-master.md`.
