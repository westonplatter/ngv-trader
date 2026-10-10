---
topics: ["frontend", "pricing", "options", "futures", "contract-qualification"]
code_dirs_or_files:
  [
    "frontend/src/components/PricingPage.tsx",
    "src/services/contract_sync.py",
    "src/api/routers/futures.py",
    "src/workers/jobs.py",
  ]
description: Pricing page UX for planning FOP and D1 entries — contract qualification flow, leg cascade, PnL chart, and API endpoints.
---

# Pricing Page UX

How the pricing page helps users plan trade entries for blended positions of futures options (FOP) and futures (D1).

## User Flow

```text
Select Instrument (/CL, /NQ, /ES)
  │
  ├── Spot price auto-fills from front-month futures
  │
  └── Add Legs (left-to-right workflow per row)
        │
        ├── Type (Call / Put / D1 / Cash)
        │     │
        │     ├── Call/Put: Strike combobox → DTE dropdown → auto-populate
        │     ├── D1: Futures contract combobox → auto-populate
        │     └── Cash: Manual strike/DTE entry
        │
        └── Qty → Calculate PnL → Plotly chart
```

## Data Architecture

### Two-tier contract system

| Layer         | Table                     | Source                      | Purpose                                                                                          |
| ------------- | ------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------ |
| **Catalog**   | `option_chain_meta`       | `reqSecDefOptParams` (IBKR) | Universe of available options. Populated by chain sync in seconds. No IBKR qualification needed. |
| **Qualified** | `contracts` (ContractRef) | `qualifyContracts` (IBKR)   | Contracts with real IBKR con_id. Required for price fetching and trading.                        |

### On-demand qualification

When a user selects an option from the catalog that hasn't been qualified yet:

1. Yellow dot appears — `contracts.qualify_and_snapshot` job enqueued
2. Worker qualifies the single contract via IBKR, inserts into `contracts`, fetches price
3. SSE job event updates the leg row with pricing data
4. Green dot appears — bid, ask, IV, und_price populate
5. Red dot if qualification or price fetch fails

### API endpoints

All `/api/v1/*` routes are served by the local FastAPI backend (`:8000`). The `/pricing-api/*` prefix is a Vite dev-server proxy that rewrites to the **nextgenvol service** at `http://localhost:8080/api/v1` — it is not part of the local FastAPI app.

| Endpoint                                           | Service            | Purpose                                                                                          |
| -------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------ |
| `GET /futures/{symbol}/term-structure`             | FastAPI (:8000)    | Futures months with prices (for D1 legs and spot price)                                          |
| `GET /futures/{symbol}/chain`                      | FastAPI (:8000)    | Full option chain catalog from `option_chain_meta`, LEFT JOINed to qualified contracts + pricing |
| `POST /jobs` with `contracts.qualify_and_snapshot` | FastAPI (:8000)    | On-demand: qualify one contract + fetch its price                                                |
| `POST /jobs` with `market_data.snapshot`           | FastAPI (:8000)    | Fetch price for already-qualified contract                                                       |
| `POST /pricing-api/expected-pnl`                   | nextgenvol (:8080) | Compute expected PnL time series (proxied via Vite; see `vite.config.ts`)                        |

## Leg Row Interaction

### Left-to-right cascade (Call/Put)

Each selection narrows the next:

1. **Type** — filters chain entries by right (C/P)
2. **Strike** — combobox with fuzzy search over available strikes for that right
3. **DTE** — dropdown of available DTEs for that type+strike combination
4. **Qty** — manual input, defaults to 1

### Auto-populated fields

When a contract is selected (via DTE dropdown or auto-select if only one DTE):

- IV (from `LatestFuturesOptions.iv`)
- Bid, Ask (from pricing data)
- Mid (computed, editable as trade price)
- Und (underlying futures price)

All auto-populated fields remain manually editable for overrides.

### Status indicators

| Dot              | Meaning                                   |
| ---------------- | ----------------------------------------- |
| (none)           | No fetch needed or idle                   |
| Yellow (pulsing) | Qualifying contract and/or fetching price |
| Green            | Price data loaded successfully            |
| Red              | Error during qualification or price fetch |

## Pricing Calculation

The expected PnL endpoint receives:

- `spot_price`, `spot_min`, `spot_max` — price range for the underlying
- `legs[]` — each with `option_type`, `strike`, `dte`, `ivstart`, `quantity`, `trade_price`
- `day_step`, `strike_step` — resolution controls

Returns `{ model_inputs, model_outputs: { min_dte, pnl_records, pnl_records_count } }`. `pnl_records[]` holds `(spot_price, days_into_future, value)` tuples, rendered as a Plotly line chart with one trace per sampled day.

## Key Files

| File                                                            | Purpose                                  |
| --------------------------------------------------------------- | ---------------------------------------- |
| `frontend/src/components/PricingPage.tsx`                       | Main pricing page with dynamic legs      |
| `frontend/src/components/ComboboxInput.tsx`                     | Reusable fuzzy-search dropdown           |
| `src/models.py` — `OptionChainMeta`                             | Unqualified option chain catalog         |
| `src/services/contract_sync.py` — `sync_futures_chain`          | Chain sync: IND → FUT → chain metadata   |
| `src/api/routers/futures.py` — `get_chain`                      | Chain catalog endpoint with pricing JOIN |
| `src/workers/jobs.py` — `handle_contracts_qualify_and_snapshot` | On-demand qualify + price fetch          |
