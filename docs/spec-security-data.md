# Spec: Security Data tables and endpoints

## Purpose

Store and serve futures contract metadata and time-series market data (prices, greeks, IV) so the app can display term structures, vol surfaces, and pre-trade snapshots without hitting IBKR in real time.

## Scope

Phase 1 focuses on **futures** and **futures options** only. Initial symbols: **CL** (Crude Oil, NYMEX) and **ES** (E-mini S&P 500, CME). Stocks and equity options are out of scope for now.

### Symbol differences

|                   | CL                                                | ES                                         |
| ----------------- | ------------------------------------------------- | ------------------------------------------ |
| Exchange          | NYMEX                                             | CME                                        |
| Multiplier        | 1,000                                             | 50                                         |
| FOP trading class | LO (standard monthly), LO1/LO2/LO3/LO4 (weeklies) | EW (weeklies), ES (monthly/quarterly)      |
| Expiry cadence    | Monthly options + weeklies                        | Quarterly futures + weekly/monthly options |
| Typical front_n   | 6                                                 | 4                                          |

The schema and endpoints are symbol-agnostic — `{symbol}` in the URL handles both. Per-symbol defaults (exchange, front_n, trading classes to sync) can live in job payloads or a future `symbols` config table.

## Existing infrastructure

- **`contracts` table** (`ContractRef` model) — already stores contract definitions (FUT, FOP, STK, OPT) synced from IBKR via `contract_sync.py`. This spec does NOT replace that table; it adds time-series data tables that reference it.
- **`contract_sync.py`** — existing job that upserts contract metadata. We extend it to also sync the Index and FOP contracts for a given underlying futures symbol.
- **Architecture boundary** — agents/API read from DB only; all IBKR interaction happens in workers.

---

## Contract hierarchy

IBKR models futures option chains as a 3-level hierarchy. We store all three levels in the `contracts` table:

```
CL Index (IND, con_id=X)          ← root; used to discover the option chain
  └── CL Futures (FUT)            ← underlying_con_id → IND con_id
        └── CL FOPs (FOP)         ← underlying_con_id → FUT con_id
```

### How discovery works (IBKR flow)

```python
from ib_async import Index

# 1. Qualify the CL Index — gives us a con_id for the root
index = Index("CL", "NYMEX", currency="USD")
ib.qualifyContracts(index)

# 2. Discover the option chain using the index's con_id
chains = ib.reqSecDefOptParams(
    underlyingSymbol=index.symbol,
    futFopExchange=index.exchange,
    underlyingSecType=index.secType,   # "IND"
    underlyingConId=index.conId,
)
# chains tells us: available expirations, strikes, trading classes,
# and which FUT con_ids are the underlyings for each expiration set
```

This means:

- The **Index** is the entry point for chain discovery (`reqSecDefOptParams`)
- The **chain result** tells us which FUT contracts are underlyings and what strikes/expiries exist
- We then fetch individual FOP contract details using that info

---

## DB tables

### `contracts` (existing)

Already stores contract definitions. The `con_id` is the join key used by the new time-series tables below.

Key fields for futures/FOP context:

- `con_id` — IBKR contract ID (unique)
- `symbol` — root symbol (e.g. "CL")
- `sec_type` — "IND", "FUT", or "FOP"
- `contract_expiry` — raw IBKR `lastTradeDateOrContractMonth` (e.g. "20260420")
- `strike`, `right` — FOP only
- `trading_class` — e.g. "CL" for futures, "LO" for standard CL options

#### New column needed: `underlying_con_id`

**Add a nullable FK column `underlying_con_id`** (int, references `contracts.con_id`) to capture the parent relationship at each level:

| Row sec_type | `underlying_con_id` points to | Example                                      |
| ------------ | ----------------------------- | -------------------------------------------- |
| IND          | null                          | CL Index is the root                         |
| FUT          | IND con_id                    | CL May'26 futures → CL Index                 |
| FOP          | FUT con_id                    | CL (LO) May14'26 70 CALL → CL May'26 futures |

This is populated during contract sync:

- **FUT → IND**: set to the Index's `con_id` (known from the sync job payload)
- **FOP → FUT**: set from IBKR's `underConId` field on `ContractDetails`, or matched via the chain result from `reqSecDefOptParams`

### Dual-table design

Each instrument type gets two tables: a `latest_*` table for hot-path API reads (single row per contract, always freshest) and a `ts_*` table for append-only history.

**Write path** — one DB transaction per snapshot batch:

1. Insert into `ts_*` (append-only, never upsert)
2. Guarded upsert into `latest_*` — only update if incoming `market_ts` is newer:

```sql
INSERT INTO latest_futures (con_id, bid, ask, last, close, volume, open_interest, market_ts, ingested_at, updated_at)
VALUES (...)
ON CONFLICT (con_id) DO UPDATE
SET bid = EXCLUDED.bid, ask = EXCLUDED.ask, last = EXCLUDED.last,
    close = EXCLUDED.close, volume = EXCLUDED.volume, open_interest = EXCLUDED.open_interest,
    market_ts = EXCLUDED.market_ts, ingested_at = EXCLUDED.ingested_at, updated_at = now()
WHERE EXCLUDED.market_ts >= latest_futures.market_ts;
```

**Read path:**

- Default API reads (term-structure, options, vol-surface) query `latest_*` — simple PK lookup, no `DISTINCT ON`
- Historical and `as_of` queries use `ts_*` — `WHERE market_ts <= :as_of`, nearest row per `con_id`

**Timestamp columns:**

- `market_ts` (timestamptz) — when IBKR observed the data (market time)
- `ingested_at` (timestamptz) — when the row was written to the DB
- `updated_at` (timestamptz) — last upsert time (`latest_*` only)

### `latest_futures` — current futures snapshot

Single row per contract, always the most recent data. PK is `con_id`.

| Column          | Type        | Nullable | Description                        |
| --------------- | ----------- | -------- | ---------------------------------- |
| `con_id`        | int         | PK, FK   | References `contracts.con_id`      |
| `bid`           | float       | yes      | Bid price                          |
| `ask`           | float       | yes      | Ask price                          |
| `last`          | float       | yes      | Last traded price                  |
| `close`         | float       | yes      | Prior session close                |
| `volume`        | int         | yes      | Session volume                     |
| `open_interest` | int         | yes      | Open interest                      |
| `market_ts`     | timestamptz | no       | When IBKR observed the data        |
| `ingested_at`   | timestamptz | no       | When the row was written to the DB |
| `updated_at`    | timestamptz | no       | Last upsert time                   |

**Indexes:** PK `(con_id)` is sufficient for all default reads.

### `ts_futures` — futures price history

Append-only time-series table for futures prices.

| Column          | Type        | Nullable | Description                        |
| --------------- | ----------- | -------- | ---------------------------------- |
| `id`            | int         | PK       | Auto-increment                     |
| `con_id`        | int         | no, FK   | References `contracts.con_id`      |
| `bid`           | float       | yes      | Bid price                          |
| `ask`           | float       | yes      | Ask price                          |
| `last`          | float       | yes      | Last traded price                  |
| `close`         | float       | yes      | Prior session close                |
| `volume`        | int         | yes      | Session volume                     |
| `open_interest` | int         | yes      | Open interest                      |
| `market_ts`     | timestamptz | no       | When IBKR observed the data        |
| `ingested_at`   | timestamptz | no       | When the row was written to the DB |

**Indexes:**

- `(con_id, market_ts DESC)` — point-in-time lookups per contract
- `(market_ts)` — time-range queries; consider BRIN at scale

### `latest_futures_options` — current FOP snapshot

Single row per contract, always the most recent data. PK is `con_id`.

| Column          | Type        | Nullable | Description                             |
| --------------- | ----------- | -------- | --------------------------------------- |
| `con_id`        | int         | PK, FK   | References `contracts.con_id` (the FOP) |
| `bid`           | float       | yes      | Bid price                               |
| `ask`           | float       | yes      | Ask price                               |
| `last`          | float       | yes      | Last traded price                       |
| `close`         | float       | yes      | Prior session close                     |
| `volume`        | int         | yes      | Session volume                          |
| `open_interest` | int         | yes      | Open interest                           |
| `iv`            | float       | yes      | Implied volatility                      |
| `delta`         | float       | yes      | Delta                                   |
| `gamma`         | float       | yes      | Gamma                                   |
| `theta`         | float       | yes      | Theta                                   |
| `vega`          | float       | yes      | Vega                                    |
| `und_price`     | float       | yes      | Underlying futures price at observation |
| `market_ts`     | timestamptz | no       | When IBKR observed the data             |
| `ingested_at`   | timestamptz | no       | When the row was written to the DB      |
| `updated_at`    | timestamptz | no       | Last upsert time                        |

**Indexes:** PK `(con_id)` is sufficient for all default reads.

### `ts_futures_options` — FOP price + greeks history

Append-only time-series table for FOP prices and greeks/IV.

| Column          | Type        | Nullable | Description                             |
| --------------- | ----------- | -------- | --------------------------------------- |
| `id`            | int         | PK       | Auto-increment                          |
| `con_id`        | int         | no, FK   | References `contracts.con_id` (the FOP) |
| `bid`           | float       | yes      | Bid price                               |
| `ask`           | float       | yes      | Ask price                               |
| `last`          | float       | yes      | Last traded price                       |
| `close`         | float       | yes      | Prior session close                     |
| `volume`        | int         | yes      | Session volume                          |
| `open_interest` | int         | yes      | Open interest                           |
| `iv`            | float       | yes      | Implied volatility                      |
| `delta`         | float       | yes      | Delta                                   |
| `gamma`         | float       | yes      | Gamma                                   |
| `theta`         | float       | yes      | Theta                                   |
| `vega`          | float       | yes      | Vega                                    |
| `und_price`     | float       | yes      | Underlying futures price at observation |
| `market_ts`     | timestamptz | no       | When IBKR observed the data             |
| `ingested_at`   | timestamptz | no       | When the row was written to the DB      |

**Indexes:**

- `(con_id, market_ts DESC)` — point-in-time lookups per option
- `(market_ts)` — time-range queries; consider BRIN at scale

---

## Endpoints (futures-focused)

### `GET /futures/{symbol}/term-structure`

Returns the futures term structure: each active FUT contract for `{symbol}` with its most recent price snapshot.

**Response shape:**

```json
[
  {
    "con_id": 555,
    "symbol": "CL",
    "local_symbol": "CLK6",
    "display_name": "CL May'26",
    "contract_expiry": "20260420",
    "contract_month": "2026-05",
    "dte": 45,
    "bid": 68.5,
    "ask": 68.55,
    "last": 68.52,
    "close": 68.3,
    "volume": 125000,
    "open_interest": 310000,
    "observed_at": "2026-03-06T14:30:00Z"
  }
]
```

**Query params:**

- `front_n` (int, default 6) — return only the first N contracts by expiry
- `as_of` (datetime, optional) — use snapshot closest to this time instead of latest

**SQL sketch (default — uses `latest_futures`):**

```sql
SELECT c.*, lf.bid, lf.ask, lf.last, lf.close, lf.volume, lf.open_interest, lf.market_ts
FROM contracts c
LEFT JOIN latest_futures lf ON lf.con_id = c.con_id
WHERE c.symbol = :symbol AND c.sec_type = 'FUT' AND c.is_active = true
ORDER BY c.contract_expiry ASC
LIMIT :front_n;
```

**SQL sketch (`as_of` — uses `ts_futures` history):**

```sql
SELECT DISTINCT ON (c.con_id)
  c.*, ts.bid, ts.ask, ts.last, ts.close, ts.volume, ts.open_interest, ts.market_ts
FROM contracts c
LEFT JOIN ts_futures ts ON ts.con_id = c.con_id AND ts.market_ts <= :as_of
WHERE c.symbol = :symbol AND c.sec_type = 'FUT' AND c.is_active = true
ORDER BY c.con_id, ts.market_ts DESC;
```

### `GET /futures/{symbol}/options`

Returns FOP contracts for a given futures symbol, enriched with latest greeks/IV.

**Query params:**

- `underlying_con_id` (int, optional) — filter to options on a specific futures contract
- `underlying_month` (str, optional) — e.g. "2026-05", filter by underlying contract month
- `strike_gte` (float, optional) — minimum strike
- `strike_lte` (float, optional) — maximum strike
- `right` (str, optional) — "C" or "P"
- `dte_lte` (int, optional) — max days to expiry
- `dte_gte` (int, optional) — min days to expiry

**Response shape:**

```json
[
  {
    "con_id": 999,
    "symbol": "CL",
    "display_name": "CL (LO) May14'26 70 CALL",
    "sec_type": "FOP",
    "strike": 70.0,
    "right": "C",
    "contract_expiry": "20260514",
    "dte": 69,
    "underlying_con_id": 555,
    "underlying_display_name": "CL May'26",
    "bid": 2.1,
    "ask": 2.15,
    "last": 2.12,
    "iv": 0.35,
    "delta": 0.42,
    "gamma": 0.03,
    "theta": -0.05,
    "vega": 0.12,
    "undPrice": 68.52,
    "observed_at": "2026-03-06T14:30:00Z"
  }
]
```

### `GET /futures/{symbol}/vol-surface`

Returns IV data organized for vol surface visualization.

**Query params:**

- `underlying_con_id` (int, optional) — single underlying
- `underlying_month` (str, optional) — e.g. "2026-05"
- `strike_gte` / `strike_lte` (float) — strike range
- `dte_lte` / `dte_gte` (int) — DTE range
- `right` (str, optional) — "C" or "P", default both
- `expiry_start` / `expiry_end` (str, optional) — filter option expiries in date range

**Response shape:** Same as `/futures/{symbol}/options` but intended for vol surface views. The key addition is grouping by `underlying_con_id` so you can see the IV term structure across different underlying futures months.

**Use case (from the spec notes):** On March 4, you want to open a calendar spread — short March 15th calls, long April 10th calls (that coincide with the May contract's OpEx). This endpoint lets you pull IV for options across two different underlying futures months side by side, filtered to the strikes and expiries you care about. The `underlying_display_name` field gives you the human-readable label (e.g. "CL May'26") rather than just an ID.

---

## Actions / Background Jobs

### Action 1: Sync Index + Futures + FOP contract definitions

**Job type:** `contracts.sync` (existing, extended)

Extend the existing `contract_sync.py` with a 3-step flow:

1. **Qualify the Index** — `ib.qualifyContracts(Index("CL", "NYMEX", currency="USD"))`. Upsert into `contracts` with `sec_type="IND"`.

2. **Discover the option chain** — `ib.reqSecDefOptParams(underlyingSymbol, futFopExchange, underlyingSecType="IND", underlyingConId=index.conId)`. This returns available expirations, strikes, trading classes, and the FUT `con_id`s that serve as underlyings.

3. **Sync FUT contracts** — for each underlying FUT `con_id` from the chain result (limited to `front_n`), fetch contract details and upsert with `underlying_con_id` → the Index's `con_id`.

4. **Sync FOP contracts** — for each FUT underlying, use the chain result's expirations/strikes/trading classes to fetch FOP contract details. Upsert with `underlying_con_id` → the parent FUT's `con_id` (from IBKR's `underConId` on `ContractDetails`).

**Payload examples:**

```json
{"symbol": "CL", "exchange": "NYMEX", "currency": "USD", "front_n": 6}
{"symbol": "ES", "exchange": "CME",   "currency": "USD", "front_n": 4}
```

`front_n` limits how many futures months deep we go for the FOP chain to avoid fetching thousands of contracts.

### Action 2: Fetch futures term structure prices

**Job type:** `market_data.futures_prices`

1. Query `contracts` for active FUT contracts for the symbol, ordered by `contract_expiry`, limited to `front_n`
2. Connect to IBKR, request market data snapshot for each contract (`reqMktData` with snapshot=True, or `reqTickers`)
3. Insert rows into `ts_futures` with bid/ask/last/close/volume/open_interest and `observed_at = now()`

**Payload:**

```json
{
  "symbol": "CL",
  "front_n": 6
}
```

**Scheduling:** Run as a periodic job (e.g. every 5 min during market hours) or on-demand via the tradebot agent.

### Action 3: Fetch futures options prices + greeks

**Job type:** `market_data.futures_options`

1. Query `contracts` for active FOP contracts matching filters (symbol, underlying_con_id, strike range, DTE range)
2. Connect to IBKR, request market data + greeks for each contract
3. Insert rows into `ts_futures_options` with bid/ask/last/IV/greeks/undPrice and `observed_at = now()`

**Payload:**

```json
{
  "symbol": "CL",
  "underlying_con_id": 555,
  "strike_gte": 65.0,
  "strike_lte": 75.0,
  "dte_lte": 45,
  "right": null
}
```

If `underlying_con_id` is omitted, fetch for all active underlying FUT contracts (capped by `front_n`).

### Action 4: Quick pre-trade snapshot

**Job type:** `market_data.snapshot`

Fetch prices/greeks for a specific set of `con_id`s. This is the "I'm about to trade these instruments, give me fresh data" action.

1. Accept a list of `con_id`s
2. Connect to IBKR, request snapshot data for each
3. Insert into the appropriate `ts_*` table based on `sec_type`
4. Return the fetched data in the job result

**Payload:**

```json
{
  "con_ids": [555, 999, 1001]
}
```

**Key property:** fast. No filtering logic — just fetch exactly what's requested. The agent or user specifies the exact contracts.

---

## Refactors

### Extract exchange map to `src/data/exchanges.py`

`_FUTURES_EXCHANGE_MAP` and `_resolve_exchange()` currently live in `src/services/tradebot_agent.py:796`. The contract sync and new market data jobs also need this mapping.

**Move to `src/data/exchanges.py`:**

- `FUTURES_EXCHANGE_MAP: dict[str, str]` (drop the leading underscore, it's now public)
- `resolve_exchange(symbol: str, sec_type: str) -> str`

**Update imports in:**

- `src/services/tradebot_agent.py` — replace local `_FUTURES_EXCHANGE_MAP` / `_resolve_exchange` with imports from `src/data/exchanges.py`
- `src/services/contract_sync.py` — import for the new sync flow
- New market data job handlers in `scripts/work_jobs.py`

### `is_active` deactivation — no changes needed

The existing deactivation logic in `contract_sync.py:101-110` filters by both `symbol` AND `sec_type`. Each level (IND, FUT, FOP) is synced as a separate spec, so syncing FUT contracts won't deactivate IND rows and vice versa. Verified safe as-is.

---

## Data retention

Append-only `ts_*` tables will grow. Options for later:

- Partition `ts_*` tables by month on `market_ts`
- Add a cleanup job that thins intraday snapshots older than N days to daily close only
- **TimescaleDB migration path:** convert `ts_futures` and `ts_futures_options` to hypertables for native retention policies, compression, and continuous aggregates. `latest_*` tables stay as regular Postgres. Adopt when history growth, storage cost, or time-range query performance warrants it.
- Not urgent for Phase 1 — CL + ES with a few months of futures and their options is manageable

## Resolved questions

1. **IBKR rate limits** — Batch requests in groups of 100 for both `qualifyContracts` and `reqTickers`. This stays within IBKR's limits.

2. **Greek source** — IBKR model greeks via `reqMktData` are expected to be populated for FOP contracts on NYMEX/CME. The market data fetch job must request `modelGreeks` and capture `ticker.modelGreeks.undPrice`. If `modelGreeks` is `None` for a FOP ticker, log a warning and store `undPrice`/greeks as null rather than failing the batch.

3. **Historical IV** — Not needed for Phase 1. Append-only design supports it later if we add a fetch cadence.
