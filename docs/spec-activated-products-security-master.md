# Spec: Activated Products & Security Master Sync

> **Status: Implemented (as of 2026-06-20).** `activated_products` table
> (seeded CL/NG/ZB/ZN/ES/NQ), IBKR discovery + 12-month sync, the
> `contracts.sync_activated` job, `GET /api/v1/activated-products`, the
> `list_activated_products` agent tool, and the Active Products UI table are
> all shipped. Remaining gap: `resolve_exchange()` in `src/data/exchanges.py`
> still raises for unknown symbols instead of being demoted to a
> non-raising hint (Functional Plan item 7).

## Complexity: 3

## Purpose

Let an operator declare a small set of "activated" futures products (CL, NG, ZB,
ZN, ES, NQ, ...) and have the system keep the next 12 calendar months of each
product's contracts in the local security master (`contracts` table). The LLM
tradebot can then resolve IBKR contract IDs for these products from the database
instead of querying IBKR directly, which is the foundation for building
multi-leg trades (e.g. a calendar butterfly: sell Oct / buy Dec / sell Feb).

## Problem

- There is no curated, persisted notion of "which products do we actively
  maintain." Contract sync is ad-hoc and one symbol at a time.
- "Pull the next 12 months" is not enforced anywhere. A plain `FUT` sync upserts
  every expiry IBKR returns, with no calendar window.
- The exchange for a symbol is resolved from a hardcoded map
  (`FUTURES_EXCHANGE_MAP` / `resolve_exchange`). Adding a new product requires a
  code change, and unknown symbols raise instead of being discoverable.
- There is no UI listing of the products we maintain, so an operator cannot see
  at a glance what is activated, what exchange was discovered, or whether a
  product is synced.

## Scope

- A new `activated_products` table seeded with CL, NG, ZB, ZN, ES, NQ.
- IBKR-driven discovery of a product's exchange and contract metadata from just
  a symbol (no exchange required up front).
- A sync that maintains the **next 12 calendar months** of FUT contracts per
  activated product in the `contracts` security master.
- A new job type to run discovery + sync, enqueueable on demand and schedulable.
- A read API and a UI listing of activated products on the market-data page.
- An LLM tool to list activated products; confirm `lookup_contract` returns
  `con_id` per contract month across all activated products.

## Non-goals

- Multi-leg spread / butterfly construction, previewing, or order routing. This
  spec only guarantees the data foundation and contract-ID lookup. Spread
  construction is a follow-up.
- Options (FOP/OPT) chain syncing for activated products. This spec covers the
  underlying FUT contracts only.
- A full product-management UI (create/edit/delete from the browser). This spec
  delivers a read-only listing; product rows are seeded and editable via the DB
  / API. Add/disambiguation UI is a follow-up.

## Current State

- `contracts` table (`ContractRef` in `src/models.py`) is the security master:
  `con_id`, `symbol`, `sec_type`, `exchange`, `contract_month`,
  `contract_expiry`, `multiplier`, `is_active`, etc.
- `src/services/contract_sync.py` syncs contracts from IBKR via
  `reqContractDetails` and upserts by `con_id`, deactivating stale rows.
  `sync_futures_chain` caps futures at `front_n` but goes through an
  Index → chain discovery path designed for options.
- `src/data/exchanges.py` `resolve_exchange()` maps symbol → exchange from a
  hardcoded dict and raises for unknown symbols.
- `src/services/contract_lookup.py` reads the security master DB-first
  (`find_contracts_with_fallback`) and returns contracts grouped by month.
- `src/services/tradebot_agent.py` exposes `lookup_contract` (DB-first, IBKR
  fallback) and `enqueue_contracts_sync_job` to the LLM. The agent must never
  import `ib_async` or talk to IBKR directly.
- `frontend/src/components/MarketDataPage.tsx` hosts the contract/chain sync
  controls (`CHAIN_SYNC_PRESETS`) and renders job tables from the API.
- Verified against installed `ib_async`: `Future('ZB')` defaults
  `exchange=''`, and `reqContractDetails` returns one `ContractDetails` per
  expiry with `.contract.exchange`, `validExchanges`, `.contract.multiplier`,
  `.contract.tradingClass`, `marketName`, `longName`, `minTick`, etc.

## Desired Outcome

- An operator can add a product by symbol alone (e.g. `ZB`); the system
  discovers the exchange and metadata from IBKR and stores it.
- For each activated product, the `contracts` table holds the FUT contracts
  expiring within the next 12 calendar months, refreshed on demand/schedule.
- The LLM can list activated products and resolve `con_id` per contract month
  for any of them, reading only from the database.
- The market-data page shows a table of activated products with discovered
  exchange, status, and synced-contract counts.

## UX Requirements

- The market-data page shows an "Active Products" table: symbol, sec_type,
  exchange (or "discovering…"), discovery status, multiplier, contract count in
  the security master, and last-synced age.
- Products pending discovery or needing disambiguation are visually
  distinguishable (status badge) from active ones.
- A discovery failure (unknown symbol, ambiguous exchange) surfaces a readable
  status and `last_error` rather than failing silently.

## Functional Plan

1. Add the `activated_products` table and seed it.
   - Seed CL, NG, ZB, ZN, ES, NQ with `sec_type=FUT`, `currency=USD`,
     `months_ahead=12`, `discovery_status=pending`, `exchange=NULL`.
2. Add IBKR discovery for a product from symbol alone.
   - `discover_product_metadata(ib, symbol, sec_type, currency)` builds
     `Future(symbol, currency=currency)` with **no exchange**, calls
     `reqContractDetails`, and returns discovered exchange(s) + metadata + the
     returned contract list.
   - Exactly one distinct exchange → that exchange. Multiple → caller marks
     `needs_disambiguation` (no silent guess). Zero results → `unknown_symbol`.
3. Add the 12-calendar-month sync.
   - `sync_activated_products(engine, host, port, client_id, ...)`: for each
     active product, discover the exchange if missing, filter the returned
     contracts to those expiring within `today → today + months_ahead`, upsert
     into `contracts`, and deactivate that product's in-DB contracts outside the
     window. Persist discovered metadata back onto the product row and update
     `discovery_status` / `last_error`.
4. Wire a job type and handler.
   - `contracts.sync_activated` enqueues the batch sync; the worker handler runs
     `sync_activated_products` using the existing IB session pool.
5. Add the read API and LLM tool.
   - `GET /api/v1/activated-products` returns product rows plus the count of
     active `contracts` rows per product.
   - `list_activated_products` agent tool reads the same data DB-first.
6. Add the UI listing.
   - "Active Products" table in `MarketDataPage.tsx` fetching the new endpoint.
7. Demote `resolve_exchange()` to an optional seed/fast-path hint; unknown
   symbols flow through IBKR discovery instead of raising.

## Data Model and State Changes

New table `activated_products` (model `ActivatedProduct` in `src/models.py`):

| Column             | Type        | Nullable    | Description                                          |
| ------------------ | ----------- | ----------- | ---------------------------------------------------- |
| `id`               | int         | PK          | Auto-increment primary key                           |
| `symbol`           | str         | no, unique  | e.g. "CL", "ZB"                                      |
| `sec_type`         | str         | no          | Default "FUT"                                        |
| `currency`         | str         | no          | Default "USD"                                        |
| `months_ahead`     | int         | no          | Calendar window to maintain. Default 12              |
| `exchange`         | str         | yes         | Discovered from IBKR; NULL until discovered          |
| `valid_exchanges`  | str         | yes         | Comma list from `ContractDetails.validExchanges`     |
| `multiplier`       | str         | yes         | Discovered contract multiplier                       |
| `trading_class`    | str         | yes         | Discovered trading class                             |
| `long_name`        | str         | yes         | `ContractDetails.longName`                           |
| `min_tick`         | float       | yes         | `ContractDetails.minTick`                            |
| `discovery_status` | str         | no          | `pending` / `active` / `needs_disambiguation` / `unknown_symbol` |
| `last_error`       | str         | yes         | Last discovery/sync error message                    |
| `is_active`        | bool        | no          | Whether the product is maintained. Default true      |
| `last_synced_at`   | timestamptz | yes         | Last successful sync time                            |
| `created_at`       | timestamptz | no          | Row creation time                                    |
| `updated_at`       | timestamptz | no          | Last update time                                     |

- State machine: `pending` → (`active` | `needs_disambiguation` |
  `unknown_symbol`). A successful sync sets `active` and `last_synced_at`.
- `contracts` table is unchanged structurally; this feature writes FUT rows into
  it for activated products and toggles `is_active` for out-of-window contracts.
- Migration creates the table and seeds the six products.

## API / Worker / Service Changes

- New router `src/api/routers/activated_products.py`:
  - `GET /api/v1/activated-products` → list of products with
    `security_master_count` (active `contracts` rows for that symbol/sec_type).
- New service functions in `src/services/contract_sync.py`:
  `discover_product_metadata`, `sync_activated_products`.
- New job type `contracts.sync_activated` in `src/services/jobs.py`; handler in
  `src/workers/jobs.py` using the IB session pool.
- New agent tool `list_activated_products` in `src/services/tradebot_agent.py`
  (read-only, DB-first, no IBKR import).
- `src/data/exchanges.py` `resolve_exchange()` no longer the hard gate; callers
  fall back to IBKR discovery when the map misses.

## Operational Considerations

- Discovery + sync is idempotent: upsert by `con_id`, deactivate out-of-window
  rows. Re-running is safe.
- One `reqContractDetails` call per product yields both the exchange and the
  contract list — no extra round trips.
- Use the existing IB session pool and connect timeouts; batch DB writes per
  product within a transaction, matching `sync_contracts`.
- The calendar window is computed at sync time from the current date, so reruns
  naturally roll the window forward and retire expired contracts.

## Risks

- A symbol may resolve to multiple exchanges (or an unexpected one). Mitigated by
  `needs_disambiguation` instead of guessing.
- IBKR may return a very large contract set for some symbols; the 12-month
  filter caps what we persist.
- `resolve_exchange` is used elsewhere; demoting it must not break existing
  callers (keep it returning the map value, only stop raising at the new call
  sites).

## Observability

- Log per product: discovered exchange, distinct-exchange count, contracts
  upserted, contracts deactivated, final `discovery_status`.
- `discovery_status` and `last_error` columns make per-product failures visible
  in the API and UI.
- Job result payload summarizes counts per product.

## Rollout

1. Migration (create + seed `activated_products`).
2. Discovery + sync service and job handler.
3. Read API + agent tool.
4. UI listing on the market-data page.
5. Run `contracts.sync_activated` against a connected gateway; verify the six
   products discover exchanges and populate the security master.

## Acceptance Criteria

- Migration creates `activated_products` seeded with CL, NG, ZB, ZN, ES, NQ.
- Running `contracts.sync_activated` populates `exchange` for each product from
  IBKR and writes only next-12-calendar-month FUT contracts into `contracts`
  (CL/NG ~12 monthly; ZB/ZN/ES/NQ ~4 quarterly).
- A product added with only a symbol (e.g. `ZB`) is discoverable end to end:
  exchange and metadata get filled, status becomes `active`.
- `GET /api/v1/activated-products` returns the rows with a correct
  `security_master_count`.
- The market-data page shows the "Active Products" table.
- `list_activated_products` and `lookup_contract` let the LLM resolve `con_id`
  per contract month for every activated product without touching IBKR.

## Open Questions

- Should add-product and disambiguation be operator actions in the UI now, or
  remain DB/API-only for this phase? (Currently scoped as a follow-up.)
- Should sync run on a fixed schedule, or stay on-demand until the spread
  feature lands? (Currently on-demand + enqueueable.)

## Related Files

- `src/models.py` — new `ActivatedProduct` model
- `alembic/versions/` — new migration (create + seed)
- `src/services/contract_sync.py` — discovery + 12-month sync
- `src/services/jobs.py`, `src/workers/jobs.py` — new job type + handler
- `src/api/routers/activated_products.py` — read API (new)
- `src/api/main.py` — register router
- `src/services/tradebot_agent.py` — `list_activated_products` tool
- `src/data/exchanges.py` — demote `resolve_exchange` to a hint
- `frontend/src/components/MarketDataPage.tsx` — Active Products table
